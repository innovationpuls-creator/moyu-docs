import { createRoot } from "react-dom/client";
import "./styles/assets.css";
import "./styles/auth.css";
import "./styles/collaboration.css";
import "./styles/console.css";
import "./styles/importexport.css";
import "./styles/shares.css";
import "./styles/task-center.css";
import { App } from "./app/app";

const root = document.querySelector<HTMLDivElement>("#app");
if (!root) throw new Error("#app root missing");

createRoot(root).render(<App />);
