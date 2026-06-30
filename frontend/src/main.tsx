import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { Landing } from "./Landing";
import "./index.css";

// Client-side front door: the marketing <Landing/> renders by default; "Launch Console" sets the
// URL hash to #console, which mounts the existing console <App/> UNCHANGED. Hash-only routing keeps
// every URL resolving to index.html — no server route, no 404 under the StaticFiles SPA mount.
function isConsole() {
  return window.location.hash.replace(/^#\/?/, "") === "console";
}

function Root() {
  const [consoleView, setConsoleView] = useState(isConsole);
  useEffect(() => {
    const onHash = () => setConsoleView(isConsole());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return consoleView ? <App /> : <Landing />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
