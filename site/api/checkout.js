// POST /api/checkout -> { clientSecret } for Stripe embedded Checkout.
// One fixed price, once, from ../public/offer.json. The buyer's password is minted here so it can ride
// in the invoice footer (Stripe's own invoice email is a second copy of it).
const { OFFER, SITE, PRODUCT, stripe, newPassword } = require("./_lib");

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  try {
    const { nonce, password } = newPassword();
    // Back to the page they bought from: / or their own /for/<token>/.
    const from = String((req.body && req.body.path) || "/");
    const back = /^\/(for\/[a-z0-9]{6,16}\/?)?$/.test(from) ? from : "/";
    const s = await stripe("checkout/sessions", {
      method: "POST",
      form: {
        ui_mode: "embedded_page",
        mode: "payment",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": String(OFFER.price_usd * 100),
        "line_items[0][price_data][product_data][name]": OFFER.name,
        "line_items[0][price_data][product_data][description]": OFFER.description,
        "payment_method_types[0]": "card",
        "payment_method_types[1]": "link",
        customer_creation: "always",
        "invoice_creation[enabled]": "true",
        "invoice_creation[invoice_data][description]": OFFER.name,
        "invoice_creation[invoice_data][custom_fields][0][name]": "Password",
        "invoice_creation[invoice_data][custom_fields][0][value]": password,
        "invoice_creation[invoice_data][custom_fields][1][name]": "Open at",
        "invoice_creation[invoice_data][custom_fields][1][value]": SITE.replace("https://", ""),
        "invoice_creation[invoice_data][footer]": `Your password: ${password}. Open the ${OFFER.thing} at ${SITE}/?pw=${password}. Brick & Mortar · hello@brickandmortar.dev`,
        "invoice_creation[invoice_data][metadata][product]": PRODUCT,
        "metadata[product]": PRODUCT,
        // for the shared Stripe router (~/Desktop/stripe-router): which product, and whose
        // handler emails the password
        "metadata[site]": SITE,
        "metadata[pw_handler]": `${SITE}/api/stripe-webhook`,
        "payment_intent_data[metadata][pw_handler]": `${SITE}/api/stripe-webhook`,
        "metadata[pw_nonce]": nonce,
        "metadata[password]": password,
        "payment_intent_data[metadata][product]": PRODUCT,
        "payment_intent_data[metadata][pw_nonce]": nonce,
        "payment_intent_data[description]": OFFER.name,
        return_url: `${SITE}${back}?paid={CHECKOUT_SESSION_ID}`,
      },
    });
    res.status(200).json({ clientSecret: s.client_secret });
  } catch (e) {
    console.error("[checkout]", e.message);
    res.status(502).json({ error: "Checkout could not start. Please try again in a minute." });
  }
};
