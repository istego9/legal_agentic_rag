import React from "react";
import ReactDOM from "react-dom/client";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import App from "./App";
import { hq21StyleVariables, hq21Theme } from "./hq21Style";
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./styles.css";

for (const [name, value] of Object.entries(hq21StyleVariables as Record<string, string>)) {
  document.documentElement.style.setProperty(name, value);
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MantineProvider theme={hq21Theme} defaultColorScheme="light">
      <Notifications />
      <App />
    </MantineProvider>
  </React.StrictMode>
);
