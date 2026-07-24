import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

/** rootElement 存储 React 应用挂载节点。 */
const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("找不到应用挂载节点");
createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
