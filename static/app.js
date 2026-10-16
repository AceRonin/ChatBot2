const productList = document.querySelector("#product-list");
const catalogCount = document.querySelector("#catalog-count");
const catalogError = document.querySelector("#catalog-error");
const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const chatMessages = document.querySelector("#chat-messages");
const chatError = document.querySelector("#chat-error");
const sendButton = document.querySelector("#send-button");

const conversation = [];

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderProduct(product) {
  const card = makeElement("article", "product-card");
  const topLine = makeElement("div", "product-topline");
  topLine.append(
    makeElement("span", "product-brand", product.brand),
    makeElement("span", "product-price", `${product.currency} ${Number(product.price).toFixed(2)}`)
  );
  const title = makeElement("h3", "", product.name);
  const description = makeElement("p", "product-description", product.description);
  const features = makeElement("div", "feature-list");
  const tags = [
    ...(Array.isArray(product.key_features) ? product.key_features.slice(0, 2) : []),
    product.battery_life_hours == null ? "Battery life not listed" : `${product.battery_life_hours}h battery`,
    product.noise_cancelling ? "Noise cancelling" : "No noise cancelling",
    product.weight_grams == null ? "Weight not listed" : `${product.weight_grams} g`,
    product.warranty_years == null ? "Warranty not listed" : `${product.warranty_years}y warranty`
  ];
  for (const tag of tags) features.append(makeElement("span", "feature-pill", tag));
  card.append(topLine, title, description, features);
  return card;
}

async function loadProducts() {
  productList.setAttribute("aria-busy", "true");
  try {
    const response = await fetch("/api/products");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load the product catalog.");
    if (!Array.isArray(data.products)) throw new Error("The product catalog response was invalid.");
    productList.replaceChildren(...data.products.map(renderProduct));
    catalogCount.textContent = `${data.products.length} ${data.products.length === 1 ? "product" : "products"}`;
  } catch (error) {
    catalogCount.textContent = "Unavailable";
    catalogError.textContent = error.message;
    catalogError.hidden = false;
  } finally {
    productList.setAttribute("aria-busy", "false");
  }
}

function addMessage(role, content) {
  const article = makeElement("article", `message ${role}-message`);
  const label = role === "assistant" ? "PRODUCT SCOUT" : "YOU";
  article.append(makeElement("span", "message-label", label), makeElement("p", "", content));
  chatMessages.append(article);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = chatInput.value.trim();
  if (!content || sendButton.disabled) return;

  chatError.hidden = true;
  chatError.textContent = "";
  addMessage("user", content);
  conversation.push({ role: "user", content });
  chatInput.value = "";
  sendButton.disabled = true;
  sendButton.querySelector("span").textContent = "Thinking…";
  const loadingMessage = makeElement("article", "message assistant-message");
  loadingMessage.setAttribute("role", "status");
  loadingMessage.append(
    makeElement("span", "message-label", "PRODUCT SCOUT"),
    makeElement("p", "", "Checking the catalog…")
  );
  chatMessages.append(loadingMessage);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: conversation.slice(-12) })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The chat request failed. Please try again.");
    if (typeof data.answer !== "string" || !data.answer.trim()) {
      throw new Error("The chat service returned an invalid response.");
    }
    conversation.push({ role: "assistant", content: data.answer });
    addMessage("assistant", data.answer);
  } catch (error) {
    chatError.textContent = error.message;
    chatError.hidden = false;
  } finally {
    loadingMessage.remove();
    sendButton.disabled = false;
    sendButton.querySelector("span").textContent = "Send";
    chatInput.focus();
  }
});

loadProducts();
