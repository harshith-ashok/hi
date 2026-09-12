import { createApp } from 'vue'
import './style.css'
// Base syntax-highlighting colors for rendered code blocks
// (lib/markdown.ts) — overridden/tuned in style.css's own `.markdown`
// rules right below its import, not left as an unrelated-looking theme
// bolted on top of this project's own dark palette.
import 'highlight.js/styles/atom-one-dark.css'
import App from './App.vue'

createApp(App).mount('#app')
