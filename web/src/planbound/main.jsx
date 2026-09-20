import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import PlanBoundApp from "./PlanBoundApp";
import { TasksProvider } from "./state/tasks";
import "./planbound.css";
import "./extras.css";

// Not wrapped in StrictMode on purpose: the original engine owns WebGL
// contexts and global listeners and is started/disposed once per page load.
createRoot(document.getElementById("root")).render(
  <HashRouter>
    <TasksProvider>
      <PlanBoundApp />
    </TasksProvider>
  </HashRouter>,
);
