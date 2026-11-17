import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
// The web's own face, so a layout reads the same on every machine (issue #38); the weights in use.
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import './index.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
