import { useEffect, useRef, useState } from "react";
import { api } from "../api";

declare global {
  interface Window {
    google?: any;
  }
}

const GIS_SRC = "https://accounts.google.com/gsi/client";
let gisLoading: Promise<void> | null = null;

function loadGis(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  gisLoading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = GIS_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      gisLoading = null;
      reject(new Error("Couldn't load Google sign-in. Check your connection."));
    };
    document.head.appendChild(script);
  });
  return gisLoading;
}

/** Google's own "Continue with Google" button; hands the ID token to `onCredential`. */
export function GoogleButton({ onCredential, onError }: { onCredential: (credential: string) => void; onError: (m: string) => void }) {
  const slot = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "off">("loading");
  const callback = useRef(onCredential);
  callback.current = onCredential;

  useEffect(() => {
    let cancelled = false;
    api
      .authConfig()
      .then(async ({ google_client_id }) => {
        if (!google_client_id) return !cancelled && setState("off");
        await loadGis();
        if (cancelled || !slot.current) return;
        window.google.accounts.id.initialize({
          client_id: google_client_id,
          callback: (r: { credential: string }) => callback.current(r.credential),
        });
        const dark = document.documentElement.dataset.theme === "dark" ||
          (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
        window.google.accounts.id.renderButton(slot.current, {
          type: "standard",
          theme: dark ? "filled_black" : "outline",
          size: "large",
          shape: "pill",
          text: "continue_with",
          width: Math.min(slot.current.clientWidth || 400, 400),
        });
        setState("ready");
      })
      .catch((err) => !cancelled && (setState("off"), onError(err.message)));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="google-slot">
      <div ref={slot} className="google-button" />
      {state === "off" && (
        <p className="form-error" role="alert">
          Google sign-in isn't set up on this server yet (GOOGLE_CLIENT_ID is empty).
        </p>
      )}
    </div>
  );
}
