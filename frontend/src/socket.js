import { io } from 'socket.io-client'

// The local web server forwards realtime traffic alongside the app.
export function initSocket() {
	const siteName = window.site_name || window.location.hostname
	return io(`${window.location.origin}/${siteName}`, {
		withCredentials: true,
		reconnectionAttempts: 5,
	})
}
