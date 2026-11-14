import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'

// "/console" → the technical operator console (Trade Gate), everything else → the customer webshop assistant.
const isConsole = location.pathname.startsWith('/console')
const Root = isConsole ? lazy(() => import('./App.tsx')) : lazy(() => import('./shop/ShopApp.tsx'))
document.title = isConsole ? 'Valio Aimo Trade Gate · Console' : 'Aimo Assistant · Valio Aimo'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense fallback={null}>
      <Root />
    </Suspense>
  </StrictMode>,
)
