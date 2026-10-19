/* paywall.js — one paywall for every Competitive Market Analysis site (pt-rates, salon-rates).
   Same file in both repos; only /offer.json differs. Pattern copied from msp-house-index:
   the page ships the free slice, /api/data hands the full table to a password, the password is
   minted at Stripe embedded Checkout and emailed by the webhook (api/_lib.js).

   Paywall.init({ onUnlock(data, via), ctx, slot }) -> draws the pay box into slot, reads ?pw= and ?paid=, restores a saved password
   Paywall.mount(el)                            -> moves the pay box into el
   Paywall.lockRow(text)                        -> html for a locked line that scrolls to the pay box
   Paywall.track(name, props)                   -> va.track AND posthog.capture, with ctx merged in
   Paywall.unlocked                             -> true once a password opened the full table
   Pages theme it with --pw-bg, --pw-ink, --pw-soft, --pw-line, --pw-card, --pw-accent. */
(function () {
  const PK = "pk_live_51TUvvcBzD4mN8eOD28H6oQkFwFHwF1SLtWxN1vHRmnSxntWFefgd33mEIVmjv8ekxWgkZft3OpPlzmVXMIeHPBwj003998hjTf";
  const BAD = "That password didn't match. Check the email from Brick & Mortar, or reply to it for help.";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const css = `
.pw-pay{margin:18px 0 0;border-radius:14px;background:var(--pw-ink,#111);color:var(--pw-bg,#fff);padding:20px 18px 18px}
.pw-line{margin:0;font-weight:800;font-size:20px;line-height:1.25;letter-spacing:-.01em}
.pw-sub{margin:8px 0 0;font-size:14px;opacity:.8}
.pw-act{display:grid;grid-template-columns:1fr;gap:8px;margin-top:16px}
@media (min-width:640px){.pw-act{grid-template-columns:1fr 1fr}}
.pw-btn{font:700 16px/1.2 inherit;font-family:inherit;padding:14px 18px;border-radius:10px;border:1.5px solid var(--pw-bg,#fff);background:var(--pw-bg,#fff);color:var(--pw-ink,#111);cursor:pointer;min-height:50px}
.pw-btn.alt{background:transparent;color:var(--pw-bg,#fff)}
.pw-btn[disabled]{opacity:.6;cursor:default}
.pw-form{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.pw-form[hidden]{display:none}
.pw-form input{flex:1 1 200px;min-width:0;font:600 16px ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;padding:11px 12px;border-radius:9px;border:1px solid currentColor;background:transparent;color:inherit}
.pw-form button{font:700 15px inherit;font-family:inherit;padding:11px 16px;border-radius:9px;border:1px solid currentColor;background:transparent;color:inherit;cursor:pointer}
.pw-err{flex-basis:100%;margin:0;font-size:14px;min-height:0}
.pw-co{margin-top:14px;border-radius:10px;overflow:hidden;background:#fff}
.pw-co:empty{display:none}
.pw-paid{margin:18px 0 0;border-radius:14px;border:1px solid var(--pw-line,#ccc);background:var(--pw-card,#fff);color:var(--pw-ink,#111);padding:20px 18px}
.pw-paid h2{margin:0;font-size:20px;line-height:1.25;text-transform:none;letter-spacing:0;color:inherit}
.pw-paid p{margin:8px 0 0;font-size:14px;color:var(--pw-soft,#555)}
.pw-lock{display:flex;justify-content:space-between;align-items:center;gap:10px;width:100%;text-align:left;font:inherit;font-weight:700;font-size:14px;color:var(--pw-ink,#111);background:var(--pw-card,#fff);border:1.5px dashed var(--pw-accent,#888);border-radius:12px;padding:12px 14px;cursor:pointer;margin-top:8px}
.pw-lock span:last-child{white-space:nowrap;color:var(--pw-accent,#888)}
.pw-unl{display:inline-block;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--pw-accent,#888)}`;

  const P = {
    unlocked: false, offer: null, ctx: {}, onUnlock: null, pw: null, el: null, co: null,
    track(name, props) {
      const data = Object.assign({}, P.ctx, props || {});
      try { window.va && window.va("event", { name, data }); } catch (e) {}
      try { window.posthog && window.posthog.capture && window.posthog.capture(name, data); } catch (e) {}
    },
    store: {
      key: () => "pw_" + (P.offer ? P.offer.product : "x"),
      get() { try { return localStorage.getItem(P.store.key()); } catch (e) { return null; } },
      set(v) { try { v ? localStorage.setItem(P.store.key(), v) : localStorage.removeItem(P.store.key()); } catch (e) {} },
    },
    lockRow(text) {
      const o = P.offer || {};
      return `<button type="button" class="pw-lock" data-pw-go>${esc(text)}<span>$${esc(o.price_usd)} →</span></button>`;
    },
    go() { P.el && P.el.scrollIntoView({ behavior: "smooth", block: "start" }); },
    mount(slot) {
      if (!slot) return;
      if (!P.el) {
        const s = document.createElement("div");
        s.innerHTML = `<section class="pw-paid" hidden aria-live="polite"><h2>Confirming your payment…</h2><p></p>
          <form class="pw-form" hidden><input name="pw" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="XXXX-XXXX-XXXX" aria-label="Password"><button>Open</button><p class="pw-err" role="alert"></p></form></section>
          <section class="pw-pay"><p class="pw-line"></p><p class="pw-sub">Your password comes by email, straight after checkout.</p>
          <div class="pw-act"><button type="button" class="pw-btn pw-buy">Get the ${esc(P.offer ? P.offer.thing : "full table")}</button><button type="button" class="pw-btn alt pw-have" aria-expanded="false">Have a password?</button></div>
          <form class="pw-form" hidden><input name="pw" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="XXXX-XXXX-XXXX" aria-label="Password"><button>Open</button><p class="pw-err" role="alert"></p></form>
          <div class="pw-co"></div></section>`;
        P.el = s;
        s.querySelector(".pw-line").textContent = P.offer ? P.offer.line : "";
        s.querySelector(".pw-buy").onclick = buy;
        s.querySelector(".pw-have").onclick = () => {
          const f = s.querySelector(".pw-pay .pw-form"), on = f.hidden;
          f.hidden = !on; s.querySelector(".pw-have").setAttribute("aria-expanded", on);
          if (on) { f.querySelector("input").focus(); P.track("password_open"); }
        };
        s.querySelectorAll("form.pw-form").forEach((f) => f.addEventListener("submit", submit));
      }
      slot.appendChild(P.el);
      P.el.hidden = P.unlocked;
    },
    async unlock(pw, via) {
      const r = await fetch("/api/data", { headers: { "x-password": pw } });
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(r.status === 401 ? BAD : (j.error || BAD)); }
      const d = await r.json();
      P.pw = pw; P.unlocked = true; P.store.set(pw);
      if (P.el) P.el.hidden = true;
      P.track("unlock", { via, kind: r.headers.get("X-Access") || "" });
      if (P.onUnlock) await P.onUnlock(d, via);
    },
    async init({ onUnlock, ctx, slot }) {
      P.onUnlock = onUnlock; P.ctx = ctx || {};
      const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
      P.offer = await fetch("/offer.json").then((r) => r.json());
      P.mount(slot);
      document.addEventListener("click", (e) => { if (e.target.closest("[data-pw-go]")) { P.track("lock_click"); P.go(); } });
      const qs = new URLSearchParams(location.search), pwq = qs.get("pw"), paidq = qs.get("paid");
      if (pwq || paidq) { qs.delete("pw"); qs.delete("paid"); history.replaceState(null, "", location.pathname + (qs.toString() ? "?" + qs : "") + location.hash); }
      const first = pwq || P.store.get();
      if (first) {
        try { await P.unlock(first, pwq ? "link" : "saved"); }
        catch (x) { if (pwq) { P.el.hidden = false; const f = P.el.querySelector(".pw-pay .pw-form"); f.hidden = false; f.querySelector("input").value = pwq; f.querySelector(".pw-err").textContent = x.message; } else P.store.set(null); }
      }
      if (paidq && !pwq) confirmPaid(paidq);
    },
  };

  async function submit(e) {
    e.preventDefault();
    const f = e.currentTarget, inp = f.querySelector("input"), err = f.querySelector(".pw-err"), b = f.querySelector("button");
    const v = inp.value.trim();
    if (!v) { err.textContent = "Enter the password from your email."; return; }
    b.disabled = true; err.textContent = ""; const t = b.textContent; b.textContent = "Opening…";
    try { await P.unlock(v, "form"); scrollTo({ top: 0, behavior: "smooth" }); } catch (x) { err.textContent = x.message; } finally { b.disabled = false; b.textContent = t; }
  }

  const loadStripe = () => window.Stripe ? Promise.resolve() : new Promise((ok, no) => { const sc = document.createElement("script"); sc.src = "https://js.stripe.com/dahlia/stripe.js"; sc.onload = ok; sc.onerror = no; document.head.appendChild(sc); });
  async function buy() {
    const s = P.el, b = s.querySelector(".pw-buy"), box = s.querySelector(".pw-co");
    s.querySelector(".pw-pay .pw-form").hidden = true; s.querySelector(".pw-have").setAttribute("aria-expanded", "false");
    P.track("checkout_open");
    if (P.co) { box.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    b.disabled = true; const t = b.textContent; b.textContent = "Loading secure checkout…";
    try {
      await loadStripe(); const st = window.Stripe(PK);
      const opts = { fetchClientSecret: () => fetch("/api/checkout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: location.pathname }) }).then((r) => r.json()).then((j) => { if (!j.clientSecret) throw new Error(j.error || "Checkout could not start."); return j.clientSecret; }) };
      P.co = await (st.createEmbeddedCheckoutPage ? st.createEmbeddedCheckoutPage(opts) : st.initEmbeddedCheckout(opts));
      P.co.mount(box); setTimeout(() => box.scrollIntoView({ behavior: "smooth", block: "start" }), 300);
    } catch (x) {
      P.co = null; const f = s.querySelector(".pw-pay .pw-form"); f.hidden = false;
      f.querySelector(".pw-err").textContent = "Checkout didn't load. Refresh the page and try again, or email aidan@brickandmortar.dev.";
    } finally { b.disabled = false; b.textContent = t; }
  }

  // Back from Stripe: ?paid=<session>. The page never shows the password; the email carries it.
  async function confirmPaid(id) {
    const box = P.el.querySelector(".pw-paid"), H = box.querySelector("h2"), T = box.querySelector("p");
    box.hidden = false; P.el.querySelector(".pw-pay").hidden = true; P.el.hidden = false;
    P.go();
    for (let i = 0; i < 6; i++) {
      try {
        const j = await fetch("/api/session-status?session_id=" + encodeURIComponent(id)).then((r) => r.json());
        if (j.paid) {
          H.textContent = "Check your email for your password";
          T.innerHTML = `${j.email ? `Sent to <b>${esc(j.email)}</b>. ` : ""}Your receipt comes from Stripe, and the invoice carries the password too. Have it? Enter it here:`;
          box.querySelector(".pw-form").hidden = false; P.track("paid"); return;
        }
        if (j.status === "expired" || j.error) break;
      } catch (e) {}
      await new Promise((r) => setTimeout(r, 2500));
    }
    H.textContent = "We couldn't confirm that payment yet";
    T.innerHTML = `If you were charged, the password is on its way to your email. Otherwise <a href="${esc(location.pathname)}">go back</a> and try again, or write to aidan@brickandmortar.dev.`;
  }

  window.Paywall = P;
})();
