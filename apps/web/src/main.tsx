import { createRoot } from "react-dom/client";
import "./styles/auth.css";
import "./styles/console.css";
import { App } from "./app/app";

const root = document.querySelector<HTMLDivElement>("#app");
if (!root) throw new Error("#app root missing");

createRoot(root).render(<App />);
