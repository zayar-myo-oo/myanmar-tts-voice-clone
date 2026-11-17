import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { createClient } from "./api/client";
import { createDemoClient, isTauri } from "./api/demo";
import "./index.css";

// Inside the desktop app use the real engine; in a plain browser use preview mode.
const preview = !isTauri();
const client = preview ? createDemoClient() : createClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App client={client} preview={preview} />
  </React.StrictMode>,
);
