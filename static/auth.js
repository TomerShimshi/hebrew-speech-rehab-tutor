// Google sign-in (Firebase Auth). The backend verifies the ID token and the email allowlist;
// this module only gets the user signed in and hands out fresh ID tokens.
import { initializeApp } from "https://www.gstatic.com/firebasejs/12.19.0/firebase-app.js";
import {
  GoogleAuthProvider,
  getAuth,
  getRedirectResult,
  onAuthStateChanged,
  signInWithPopup,
  signInWithRedirect,
  signOut as fbSignOut,
} from "https://www.gstatic.com/firebasejs/12.19.0/firebase-auth.js";

let auth = null;

export async function initAuth(onUserChanged) {
  const res = await fetch("api/config");
  const { firebase } = await res.json();
  if (!firebase.apiKey) throw new Error("Firebase is not configured on the server");
  auth = getAuth(initializeApp(firebase)); // login persists on this device (local persistence)
  getRedirectResult(auth).catch(() => {}); // completes a redirect sign-in, if one was used
  onAuthStateChanged(auth, onUserChanged);
}

export async function signIn() {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  try {
    await signInWithPopup(auth, provider);
  } catch (err) {
    // Popups can be blocked (e.g. some tablet browsers): fall back to a full-page redirect.
    if (err?.code === "auth/popup-blocked" || err?.code === "auth/operation-not-supported-in-this-environment") {
      await signInWithRedirect(auth, provider);
    } else if (err?.code !== "auth/popup-closed-by-user" && err?.code !== "auth/cancelled-popup-request") {
      throw err;
    }
  }
}

export function signOut() {
  return fbSignOut(auth);
}

// Fresh ID token for API calls (Firebase refreshes it automatically before it expires).
export async function idToken() {
  if (!auth?.currentUser) throw new Error("not signed in");
  return auth.currentUser.getIdToken();
}
