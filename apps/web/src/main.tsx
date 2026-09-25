import { createRoot } from "react-dom/client";
import "./styles/assets.css";
import "./styles/auth.css";
import "./styles/collaboration.css";
import "./styles/console.css";
import "./styles/importexport.css";
import "./styles/shares.css";
import "./styles/task-center.css";
import { App } from "./app/app";

/** Legacy auth pages share the React Router history through this adapter. */
export function navigate(path: string): void {
	window.history.pushState({}, "", path);
	window.dispatchEvent(new PopStateEvent("popstate"));
}

const root = document.querySelector<HTMLDivElement>("#app");
if (!root) throw new Error("#app root missing");

createRoot(root).render(<App />);
