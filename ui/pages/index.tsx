import {useEffect, useReducer, useRef, useState} from 'react'
import Head from 'next/head'
import {useSelector, useDispatch} from 'react-redux'
import * as Icons from 'heroicons-react'
import clsx from 'clsx'
import {w3cwebsocket as WebSocket} from 'websocket'

const client = new WebSocket('ws://192.168.0.146:8765')

const DEFAULT_STATE = {
    detents: 6,
    pos: 0
}

function Circle({detents, pos}) {
    const circle_size = 500
    const dot_size = 50

    const rot = -360 * (pos / detents)

    const remapped_pos = (detents - pos) % detents

    return <div className="relative">
        <div className="rounded-full absolute top-0 left-0 bg-blue-800" style={{width: circle_size, height: circle_size}} />
        <div className="absolute" style={{width: circle_size, height: circle_size, transform: `rotate(${rot}deg)`}}>
            <div className="bg-red-500 absolute rounded-full" style={{width: dot_size, height: dot_size, left: (circle_size-dot_size)/2, top: -dot_size*0.4}} />
        </div>
        <div className="absolute flex items-center justify-center text-white text-6xl" style={{width: circle_size, height: circle_size}}>
            {remapped_pos} / {detents}
        </div>
    </div>
}

const stateReducer = (state=DEFAULT_STATE, action) => {
    switch (action.type) {
        case 'UPDATE':
            return Object.assign({}, state, action.update)
        default:
            return state
    }
}

export default function IndexPage() {
    const [state, dispatchState] = useReducer(stateReducer, DEFAULT_STATE)
    const state_ref = useRef(state)
    const [connected, setConnected] = useState(false)

    const updateState = (update, send_update=false) => {
        const state = state_ref.current
        const new_state = Object.assign({}, state, update)
        if (send_update) {
            console.log("> STATE", new_state)
            client.send(JSON.stringify({type: 'set_state', state: new_state}))
        } else {
            console.log("+ STATE", new_state)
            state_ref.current = new_state
            dispatchState({type: 'UPDATE', update: update})
        }
    }

    const changePos = (e) => {
        let pos = parseFloat(e.target.value)
        pos = (state.detents - pos) % state.detents
        updateState({pos}, true)
    }

    const changeDetents = (e) => {
        const detents = parseFloat(e.target.value)
        updateState({detents}, true)
    }

    useEffect(() => {
        client.onopen = () => {
            setConnected(true)
            client.send(JSON.stringify({type: 'get_state'}))
        }
        client.onmessage = (message_raw: any) => {
            try {
                const message = JSON.parse(message_raw.data)
                if (message.type == 'state') {
                    const new_state = message.state
                    console.log('< STATE', new_state)
                    updateState(new_state)
                } else {
                    console.log("unknown message", message)
                }
            } catch (err) {
                console.error("Invalid WS message", message_raw)
                console.error(err)
            }
        }
    }, [])

    return <div>
        <Head>
            <title>Virtual detents</title>
        </Head>
        <input type="number" value={state.detents} onChange={changeDetents} className="hidden" />
        <div className="flex flex-row gap-4">
            {[4, 8, 16, 32].map((n) => {
                const setter_class = clsx(
                    "px-6 py-2 border border-gray-500 text-xl cursor-pointer",
                    {"bg-blue-500 text-white": (n == state.detents)}
                )
                return <a className={setter_class} onClick={() => updateState({detents: n}, true)} key={n}>{n}</a>
            })}
        </div>
        <div className="p-16 mx-auto">
            <Circle detents={state.detents} pos={state.pos} />
        </div>
    </div>
}
