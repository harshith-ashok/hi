import { ref, watch } from 'vue'

export type Theme = 'auto' | 'light' | 'dark'
const theme = ref<Theme>((localStorage.getItem('theme') as Theme) || 'auto')
const media = window.matchMedia('(prefers-color-scheme: dark)')
const dark = ref(false)

function apply() {
  dark.value = theme.value === 'dark' || (theme.value === 'auto' && media.matches)
  document.documentElement.classList.toggle('dark', dark.value)
  document.documentElement.style.colorScheme = dark.value ? 'dark' : 'light'
}

watch(theme, (value) => { localStorage.setItem('theme', value); apply() }, { immediate: true })
media.addEventListener('change', apply)

export function useTheme() {
  const cycle = () => (theme.value = ({ auto: 'light', light: 'dark', dark: 'auto' } as Record<Theme, Theme>)[theme.value])
  return { theme, dark, cycle }
}
