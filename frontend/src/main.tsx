import React from "react";
import ReactDOM from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "./styles.css";
import App from "./App";
import DepotInbox from "./components/DepotInbox";

// ?view=depot is RPM Hire's side. No router: two views are not worth one.
const depot = new URLSearchParams(window.location.search).get("view") === "depot";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {depot ? <DepotInbox /> : <App />}
  </React.StrictMode>,
);
