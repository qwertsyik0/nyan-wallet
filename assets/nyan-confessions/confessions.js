const form = document.querySelector("#confession-form");
const field = document.querySelector("#confession");
const count = document.querySelector("#count");
const submit = form.querySelector("button");
const submitStatus = document.querySelector("#submit-status");
const feedStatus = document.querySelector("#feed-status");
const posts = document.querySelector("#posts");
const more = document.querySelector("#more");
const interactionTemplate = document.querySelector("#post-interactions");
const feedPath = "/api/nyan-confessions/feed";
const dateFormat = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Moscow",
});

let cursor = null;
let ownerHeaders = null;

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.headers.get("Content-Type")?.includes("application/json")) {
    throw new Error();
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.detail);
  return data;
}

function postJson(path, payload, headers = {}) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(payload),
  });
}

function renderEntry(entry, className) {
  const article = document.createElement("article");
  article.className = className;

  const meta = document.createElement("div");
  meta.className = "meta";
  const author = document.createElement("strong");
  author.textContent = "Анонимно";
  const date = document.createElement("time");
  date.dateTime = new Date(entry.created_at).toISOString();
  date.textContent = dateFormat.format(entry.created_at);
  meta.append(author, date);

  const body = document.createElement("p");
  body.className = "text";
  body.textContent = entry.body;
  article.append(meta, body);
  return article;
}

async function loadOwner() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (!params.has("owner")) return;

  const headers = { "X-Telegram-Init-Data": params.get("owner") };
  history.replaceState(history.state, "", location.pathname + location.search);
  try {
    const data = await api("/api/nyan-confessions/owner-heart/access", { headers });
    if (data.owner === true) ownerHeaders = headers;
  } catch (error) {
    document.querySelector("#owner-status").textContent =
      error.message || "Не удалось войти в режим владельца. Открой ссылку в Telegram заново.";
  }
}

function mountOwnerHeart(controls, post, path) {
  const heart = controls.querySelector(".owner-heart");
  const badge = controls.querySelector(".owner-heart-badge");
  const status = controls.querySelector(".owner-heart-status");

  function show(liked) {
    badge.hidden = !liked;
    heart.textContent = liked ? "❤️" : "🤍";
    heart.setAttribute("aria-pressed", String(liked));
    heart.setAttribute("aria-label", liked ? "Снять сердечко от Кверта" : "Поставить сердечко от Кверта");
  }

  show(post.liked_by_owner === true);
  if (!ownerHeaders) return;
  heart.hidden = false;
  heart.addEventListener("click", async () => {
    heart.disabled = true;
    status.textContent = "";
    try {
      const result = await postJson(path + "/owner-heart", { liked: badge.hidden }, ownerHeaders);
      show(result.liked_by_owner);
    } catch (error) {
      status.textContent = error.message || "Не удалось сохранить сердечко.";
    } finally {
      heart.disabled = false;
    }
  });
}

function mountReactions(controls, post, path) {
  const buttons = [...controls.querySelectorAll("[data-reaction]")];
  const status = controls.querySelector(".reaction-status");
  const storageKey = "nyan-confessions.reaction." + post.id;
  let choice = {};

  function restoreChoice() {
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey));
      if (typeof stored?.key === "string") choice = stored;
    } catch {
      // Reactions still work for the current page with storage disabled.
    }
  }

  function saveChoice() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(choice));
    } catch {
      // Keep the key in memory for the rest of this visit.
    }
  }

  function updateCounts({ likes = 0, dislikes = 0 }) {
    for (const button of buttons) {
      const like = button.dataset.reaction === "1";
      const count = like ? likes : dislikes;
      button.querySelector("[data-count]").textContent = count;
      button.setAttribute("aria-label", `${like ? "Лайк" : "Дизлайк"} · ${count}`);
      button.setAttribute("aria-pressed", String(Number(button.dataset.reaction) === choice.value));
    }
  }

  restoreChoice();
  updateCounts(post);
  for (const button of buttons) {
    button.addEventListener("click", async () => {
      restoreChoice();
      const selected = Number(button.dataset.reaction);
      const reaction = choice.value === selected ? 0 : selected;
      if (!/^[a-f0-9]{32}$/.test(choice.key || "")) {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        choice.key = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
        saveChoice();
      }
      buttons.forEach(item => { item.disabled = true; });
      status.textContent = "";
      try {
        const result = await postJson(path + "/reaction", { key: choice.key, reaction });
        choice.value = result.reaction;
        saveChoice();
        updateCounts(result);
      } catch (error) {
        status.textContent = error.message || "Не удалось сохранить реакцию.";
      } finally {
        buttons.forEach(item => { item.disabled = false; });
      }
    });
  }
}

function mountComments(controls, post, path) {
  const toggle = controls.querySelector(".comments-toggle");
  const panel = controls.querySelector(".comments");
  const form = panel.querySelector(".comment-form");
  const field = form.querySelector("textarea");
  const submit = form.querySelector("button");
  const status = panel.querySelector(".comment-status");
  const list = panel.querySelector(".comment-list");
  const older = panel.querySelector(".comments-more");
  const rendered = new Set();
  let loaded = false;
  let busy = false;
  let before = null;

  panel.id = "comments-" + post.id;
  toggle.setAttribute("aria-controls", panel.id);

  function updateCount(total = 0) {
    toggle.textContent = total ? `Комментарии · ${total}` : "Комментировать";
  }

  function addComment(entry, prepend = false) {
    if (rendered.has(entry.id)) return;
    rendered.add(entry.id);
    const article = renderEntry(entry, "post-comment");
    if (prepend) list.prepend(article);
    else list.append(article);
  }

  async function loadComments() {
    if (busy) return;
    busy = true;
    older.disabled = true;
    submit.disabled = true;
    status.dataset.state = "";
    status.textContent = "Загружаем комментарии…";
    try {
      const data = await api(path + (before === null ? "" : "?before=" + before));
      data.comments.forEach(entry => addComment(entry));
      updateCount(data.total);
      before = data.before;
      loaded = true;
      older.textContent = "Показать предыдущие";
      older.hidden = before === null;
      status.textContent = rendered.size ? "" : "Пока комментариев нет.";
    } catch (error) {
      status.dataset.state = "error";
      status.textContent = error.message || "Не удалось загрузить комментарии.";
      older.textContent = "Повторить загрузку";
      older.hidden = false;
    } finally {
      busy = false;
      older.disabled = false;
      submit.disabled = false;
    }
  }

  updateCount(post.comment_count);
  toggle.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    toggle.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden && !loaded) loadComments();
  });
  older.addEventListener("click", loadComments);

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy) return;
    const body = field.value.trim();
    if (!body) {
      status.dataset.state = "error";
      status.textContent = "Напиши комментарий.";
      return;
    }

    busy = true;
    submit.disabled = true;
    older.disabled = true;
    field.readOnly = true;
    status.dataset.state = "";
    status.textContent = "Отправляем…";
    try {
      const data = await postJson(path, { body });
      addComment(data.comment, true);
      updateCount(data.total);
      field.value = "";
      status.textContent = "Комментарий опубликован.";
    } catch (error) {
      status.dataset.state = "error";
      status.textContent = error.message || "Не удалось отправить комментарий.";
    } finally {
      busy = false;
      field.readOnly = false;
      submit.disabled = false;
      older.disabled = false;
    }
  });
}

function renderPost(post, prepend = false) {
  const id = "post-" + post.id;
  if (document.getElementById(id)) return;
  const article = renderEntry(post, "post");
  article.id = id;
  const controls = interactionTemplate.content.cloneNode(true);
  const path = feedPath + "/" + post.id;
  mountReactions(controls, post, path);
  mountOwnerHeart(controls, post, path);
  mountComments(controls, post, path + "/comments");
  article.append(controls);

  if (prepend) posts.prepend(article);
  else posts.append(article);
}

async function loadPosts() {
  more.disabled = true;
  try {
    const path = cursor === null ? feedPath : feedPath + "?before=" + cursor;
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
    const post = await postJson(feedPath, { body });
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
loadOwner().finally(loadPosts);
