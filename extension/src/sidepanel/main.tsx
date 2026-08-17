import { createRoot } from 'react-dom/client';
import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import { App } from './App';
import { applyStoredTheme } from './theme';
import '@/styles/tailwind.css';

// Resolve theme before first paint to avoid a flash of the wrong palette.
applyStoredTheme();

const container = document.getElementById('root');
if (!container) throw new Error('Root element not found');
createRoot(container).render(<App />);
