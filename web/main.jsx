import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "../evolvable/ui/App.jsx";
import "../evolvable/ui/styles.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
