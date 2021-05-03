import asyncio
import websockets
import math
import moteus
import time
import sys
import json

INIT_VELOCITY = 1 # How fast to get to zero when starting
VELOCITY = 2.0
MAX_TORQUE = 0.04
FF_TORQUE = 0.0
KP_SCALE = 1.0
KD_SCALE = 0.25
DETENTS = 8
POS_DIFF = 0.01
SLEEP_TIME = 0.001 # Must be less than 0.01

def fit(unscaled, from_min, from_max, to_min, to_max):
    if unscaled < from_min:
        return to_min
    if unscaled > from_max:
        return to_max
    return (to_max - to_min) * (unscaled - from_min) / (from_max - from_min) + to_min

async def get_pos(c):
    state = await c.set_position(position=math.nan, query=True)
    return state.values[moteus.Register.POSITION]

async def init(c):
    await c.set_stop()
    cur_pos = await get_pos(c)
    next_pos = 0
    while math.fabs(cur_pos - next_pos) > POS_DIFF:
        state = await c.set_position(
            position=math.nan,
            stop_position=next_pos,
            velocity=INIT_VELOCITY,
            query=True
        )
        cur_pos = state.values[moteus.Register.POSITION]
        await asyncio.sleep(SLEEP_TIME)

async def move_to(c, next_pos):
    cur_pos = await get_pos(c)
    while math.fabs(cur_pos - next_pos) > POS_DIFF:
        state = await c.set_position(
            position=math.nan,
            stop_position=next_pos,
            velocity=VELOCITY,
            maximum_torque=MAX_TORQUE,
            feedforward_torque=FF_TORQUE,
            kp_scale=KP_SCALE,
            kd_scale=KD_SCALE,
            query=True
        )
        cur_pos = state.values[moteus.Register.POSITION]
        await asyncio.sleep(SLEEP_TIME)

async def hold(c, hold_time: float):
    time_end = time.time() + hold_time
    while time.time() < time_end:
        state = await c.set_position(
            position=math.nan,
            maximum_torque=MAX_TORQUE,
            query=True
        )
        await asyncio.sleep(SLEEP_TIME)

SNAP_START = 0.5
FALLOFF_START = 0.2
FALLOFF_END = SNAP_START
FALLOFF_SCALE = 16

async def control_loop(settings_queue, state_queue):
    c = moteus.Controller()

    await init(c)
    await hold(c, 0.5)

    cur_pos = await get_pos(c)
    detents = DETENTS
    detent_pos = cur_pos
    i = 0

    try:
        while True:
            # Look for new settings
            try:
                new_settings = settings_queue.get_nowait()
                print("[new_settings]", new_settings)
                if 'detents' in new_settings:
                    detents = new_settings['detents']
                    nearest = round(detent_pos * detents) / detents
                    detent_pos = nearest
                    # await move_to(c, nearest)
                    pos = round(detent_pos * detents) % detents
                    print(f"pos = {pos}")
                    await state_queue.put({'pos': pos})
                if 'pos' in new_settings:
                    pos = new_settings['pos']
                    detent_pos = pos / detents
                    await state_queue.put({'pos': pos})
                    await move_to(c, detent_pos)
            except asyncio.QueueEmpty:
                pass

            detent_size = 1.0 / detents
            moved_frac = math.fabs(cur_pos - detent_pos) / detent_size
            torque_mul = 1.0
            kp_mul = 1.0
            kd_mul = 1.0

            if moved_frac > SNAP_START:
                if cur_pos > detent_pos:
                    detent_pos += detent_size
                else:
                    detent_pos -= detent_size
                moved_frac = 1 - moved_frac
                pos = round(detent_pos * detents) % detents
                print(f"pos = {pos}")
                await state_queue.put({'pos': pos})

            if moved_frac > FALLOFF_START:
                # From 0.15 to 0.5 should map from 1 to 4
                # kp_mul = fit(moved_frac, FALLOFF_START, FALLOFF_END, 1, FALLOFF_SCALE)
                # t /= 2
                # kp_div = FALLOFF_SCALE
                pass

            # torque_mul = fit(moved_frac, 0, 0.2, 4, 1)
            # kp_mul = fit(moved_frac, 0.1, SNAP_START, 1, 0.2)

            state = await c.set_position(
                position=math.nan,
                stop_position=detent_pos,
                velocity=VELOCITY,
                maximum_torque=MAX_TORQUE * torque_mul,
                kp_scale=KP_SCALE * kp_mul,
                kd_scale=KD_SCALE * kd_mul,
                query=True
            )

            # if (i % 100) == 0:
            #     print('T', state.values[moteus.Register.TORQUE] * 100, '\t\t', 'V', state.values[moteus.Register.VELOCITY] * 100)

            cur_pos = state.values[moteus.Register.POSITION]

            i += 1
            await asyncio.sleep(SLEEP_TIME)

    except Exception as err:
        print(err)
        print("Stopping...")
        await c.set_stop()
        sys.exit()

connected = set()

async def send_or_fail(c, message):
    try:
        await c.send(message)
    except:
        print("or fail")

def create_settings_handler(settings_queue, state_queue):
    async def settings_handler(websocket, path):
        print("++ Started settings socket")
        connected.add(websocket)

        async for settings_json in websocket:
            settings = json.loads(settings_json)
            print(f"R < {settings}")
            await settings_queue.put(settings)
            if connected:
                re_settings_json = json.dumps({'type': 'settings', 'settings': settings})
                await asyncio.wait([c.send(re_settings_json) for c in connected])
            else:
                print('resend: none connected')

    return settings_handler

async def send_or_disconnect(ws, message):
    try:
        await ws.send(message)
    except:
        print("failed to send")
        connected.remove(ws)

async def state_sender(state_queue):
    while True:
        state = await state_queue.get()
        message = {'type': 'state', 'state': state}
        message_json = json.dumps(message)
        print(f'S > {message_json}')
        if connected:
            await asyncio.wait([send_or_disconnect(c, message_json) for c in connected])
        else:
            print('send: none connected')

async def main():
    print('-'*60)
    settings_queue = asyncio.Queue()
    state_queue = asyncio.Queue()

    await websockets.serve(create_settings_handler(settings_queue, state_queue), "0.0.0.0", 8765)
    await asyncio.wait([
        control_loop(settings_queue, state_queue),
        state_sender(state_queue),
    ])

if __name__ == '__main__':
    asyncio.run(main())
