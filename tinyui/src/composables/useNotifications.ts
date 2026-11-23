import { ref, watch } from 'vue'

// Desktop notifications from the browser, only while this tab is hidden: a reply finished, or an approval is waiting.
// Permission is asked once, from the first message you send (a click or key press is required to ask).
export const notificationsOn = ref(localStorage.getItem('notify') !== '0')
watch(notificationsOn, (on) => localStorage.setItem('notify', on ? '1' : '0'))

const supported = typeof Notification !== 'undefined'
export const permission = ref<NotificationPermission | 'unsupported'>(supported ? Notification.permission : 'unsupported')

/** Ask the browser for permission, if it has not been asked and notifications are on. Call it from a user action. */
export async function askOnce() {
  if (!supported || !notificationsOn.value || Notification.permission !== 'default') return
  permission.value = await Notification.requestPermission()
}

/** Show a notification if they are on, allowed, and this tab is not the one you are looking at. */
export function notifyHidden(title: string, body: string, tag: string) {
  if (!supported || !notificationsOn.value || Notification.permission !== 'granted' || !document.hidden) return
  const n = new Notification(title, { body: body.slice(0, 140), tag })
  n.onclick = () => { window.focus(); n.close() }
}
