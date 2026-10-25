"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const js = fs.readFileSync("wallet_launch_recovery_20261019.js", "utf8");
const html = fs.readFileSync("index.html", "utf8");
assert.ok(html.includes("wallet_launch_recovery_20261019.js"));
assert.ok(html.indexOf("wallet_launch_recovery_20261019.js") < html.indexOf("./app.js?"));
assert.ok(html.includes("app.js?v=20261025-no-abort1"));

function fixture(hasLoader = true) {
    let now = 0;
    const timers = [];
    const events = {};
    const reloaded = [];
    const calls = [];
    const classes = new Set();
    const nodes = {
        "loading-view": {
            classList: {
                contains: value => classes.has(value),
                add: value => classes.add(value)
            }
        },
        "loading-status": { textContent: "подключаемся" },
        "loading-hint": { textContent: "ожидание" },
        "loading-retry": {
            hidden: true,
            addEventListener: (name, callback) => { events["retry:" + name] = callback; }
        }
    };
    const win = {
        __nyanWalletReady: false,
        setTimeout(fn, delay) { timers.push({at: now + delay, fn}); },
        addEventListener(name, fn) { events["window:" + name] = fn; },
        location: {reload: () => reloaded.push(true)}
    };
    if (hasLoader) win.loadWallet = () => { calls.push(now); return Promise.resolve(); };
    const document = {
        hidden: false,
        getElementById: key => nodes[key] || null,
        addEventListener(name, fn) { events["document:" + name] = fn; }
    };
    vm.runInNewContext(js, {window: win, document, Date: {now: () => now}, Promise});
    function advance(duration) {
        const end = now + duration;
        while (true) {
            timers.sort((a,b) => a.at - b.at);
            const next = timers[0];
            if (!next || next.at > end) break;
            timers.shift();
            now = next.at;
            next.fn();
        }
        now = end;
    }
    return {win, document, nodes, events, reloaded, calls, advance};
}

const app = fixture();
app.win.__nyanWalletLoadInFlight = true;
app.advance(8000);
assert.equal(app.calls.length, 0, "8s recovery must not abort an active wallet fetch");
assert.equal(app.nodes["loading-retry"].hidden, false);
assert.match(app.nodes["loading-hint"].textContent, /не закрывая/);
app.advance(12000);
assert.equal(app.calls.length, 0, "20s recovery must not abort an active wallet fetch");
app.events["window:focus"]();
assert.equal(app.calls.length, 0, "focus must not abort an active fetch");
app.win.__nyanWalletLoadInFlight = false;
app.advance(5000);
app.events["window:focus"]();
assert.equal(app.calls.length, 1, "retry an idle stalled boot on page focus");
app.win.__nyanWalletReady = true;
app.advance(30000);
app.events["window:online"]();
assert.equal(app.calls.length, 1, "no new retries after wallet is ready");
app.events["retry:click"]();
assert.equal(app.reloaded.length, 0, "normal button handled by app.js");

const absentApp = fixture(false);
absentApp.advance(8000);
assert.equal(absentApp.nodes["loading-retry"].hidden, false);
absentApp.events["retry:click"]();
assert.equal(absentApp.reloaded.length, 1, "manual fallback if app.js did not load");

console.log("PASS: first launch, slow retries, page resume, ready guard and manual fallback");
