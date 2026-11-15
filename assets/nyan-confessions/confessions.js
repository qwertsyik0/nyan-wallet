const form = document.querySelector("#confession-form");
const field = document.querySelector("#confession");
const count = document.querySelector("#count");
const submit = form.querySelector("button");
const submitStatus = document.querySelector("#submit-status");
const feedStatus = document.querySelector("#feed-status");
const posts = document.querySelector("#posts");
const more = document.querySelector("#more");
const dateFormat = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Moscow",
});

let cursor = null;

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.headers.get("Content-Type")?.includes("application/json")) {
    throw new Error();
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

function renderPost(post, prepend = false) {
  if (document.getElementById("post-" + post.id)) return;

  const article = document.createElement("article");
  article.className = "post";
  article.id = "post-" + post.id;

  const meta = document.createElement("div");
  meta.className = "meta";
  const author = document.createElement("strong");
  author.textContent = "Анонимно";
  const date = document.createElement("time");
  date.dateTime = new Date(post.created_at).toISOString();
  date.textContent = dateFormat.format(post.created_at);
  meta.append(author, date);

  const body = document.createElement("p");
  body.className = "text";
  body.textContent = post.body;
  article.append(meta, body);

  if (prepend) posts.prepend(article);
  else posts.append(article);
}

async function loadPosts() {
  more.disabled = true;
  try {
    const path = cursor === null ? "/api/nyan-confessions/feed" : "/api/nyan-confessions/feed?before=" + cursor;
    const data = await api(path);
    data.posts.forEach(post => renderPost(post));
    cursor = data.before;
    feedStatus.textContent = "Пока признаний нет.";
    feedStatus.hidden = posts.childElementCount > 0;
    more.textContent = "Показать ещё";
    more.hidden = cursor === null;
  } catch {
    feedStatus.textContent = "Не удалось загрузить ленту.";
    feedStatus.hidden = false;
    more.textContent = "Повторить";
    more.hidden = false;
  } finally {
    more.disabled = false;
  }
}

function updateCount() {
  count.textContent = field.value.length + " / " + field.maxLength;
}

field.addEventListener("input", () => {
  field.setCustomValidity("");
  updateCount();
});

form.addEventListener("submit", async event => {
  event.preventDefault();
  const body = field.value.trim();
  if (!body) {
    field.setCustomValidity("Напиши признание.");
    field.reportValidity();
    return;
  }

  submit.disabled = true;
  field.readOnly = true;
  submitStatus.textContent = "Публикуем…";
  submitStatus.dataset.state = "";
  try {
    const post = await api("/api/nyan-confessions/feed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    });
    field.value = "";
    updateCount();
    renderPost(post, true);
    feedStatus.hidden = true;
    submitStatus.textContent = "Признание опубликовано.";
  } catch (error) {
    submitStatus.textContent = error.message || "Не удалось опубликовать. Попробуй ещё раз.";
    submitStatus.dataset.state = "error";
  } finally {
    field.readOnly = false;
    submit.disabled = false;
  }
});

more.addEventListener("click", loadPosts);
submit.disabled = false;
updateCount();
feedStatus.textContent = "Загружаем признания…";
feedStatus.hidden = false;
loadPosts();
