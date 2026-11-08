"use strict";
const form = document.getElementById("form");
const input = document.getElementById("value");
const label = document.getElementById("label");
const submit = document.getElementById("submit");
const cancel = document.getElementById("cancel");
const message = document.getElementById("message");
const error = document.getElementById("error");
const title = document.getElementById("step-title");
let csrf = "";
let step = "send";
let busy = false;
async function request(path, body) {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf},
    body: JSON.stringify(body),
    cache: "no-store",
    redirect: "error"
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Unable to complete this request.");
  return data;
}
function render(data) {
  step = data.step;
  message.textContent = data.message || "";
  const done = step === "done" || step === "cancelled";
  form.hidden = done;
  cancel.hidden = done;
  input.hidden = step === "send" || done;
  label.hidden = input.hidden;
  input.required = !input.hidden;
  input.value = "";
  title.textContent = {send:"Ready to connect", code:"Check your Telegram", password:"One more step", done:"You're connected", cancelled:"Login cancelled"}[step];
  document.getElementById("count").textContent = {send:"01 / 03",code:"02 / 03",password:"03 / 03",done:"COMPLETE",cancelled:"CLOSED"}[step];
  label.textContent = step === "password" ? "Two-step verification password" : "Verification code";
  input.type = step === "password" ? "password" : "text";
  input.inputMode = step === "password" ? "text" : "numeric";
  input.autocomplete = step === "password" ? "current-password" : "one-time-code";
  input.maxLength = step === "password" ? 1024 : 8;
  submit.textContent = step === "send" ? "Send verification code →" : "Connect account →";
  if (!input.hidden) input.focus();
}
async function act(action) {
  if (busy) return;
  busy = true;
  submit.disabled = true;
  cancel.disabled = true;
  error.textContent = "";
  let value = input.value;
  input.value = "";
  try {
    const operation = request("/api/action", {action, value});
    value = "";
    render(await operation);
  } catch (failure) {
    error.textContent = failure.message || "Connection failed. Please try again.";
  } finally {
    value = "";
    busy = false;
    submit.disabled = false;
    cancel.disabled = false;
  }
}
form.addEventListener("submit", event => {
  event.preventDefault();
  act(step === "send" ? "send" : "verify");
});
cancel.addEventListener("click", () => act("cancel"));
(async () => {
  let token = location.hash.slice(1);
  history.replaceState(null, "", "/");
  if (!token) {
    title.textContent = "Start in your Telegram bot";
    message.textContent = "Send /login followed by your phone number to receive a private login link. If you refreshed this page, request a new link.";
    return;
  }
  try {
    const operation = request("/api/exchange", {token});
    token = "";
    const data = await operation;
    csrf = data.csrf;
    render({step:"send", message:`Connect your Telegram account ending in ${data.suffix}. Keep this page open until you finish.`});
  } catch (failure) {
    title.textContent = "This link is unavailable";
    message.textContent = failure.message || "Please request a new /login from your bot.";
  } finally {
    token = "";
  }
})();
