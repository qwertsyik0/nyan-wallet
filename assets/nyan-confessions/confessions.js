const form = document.querySelector("#confession-form");
const field = document.querySelector("#confession");
const count = document.querySelector("#count");
const submit = form.querySelector("button");
const submitStatus = document.querySelector("#submit-status");
const feedStatus = document.querySelector("#feed-status");
const posts = document.querySelector("#posts");
const more = document.querySelector("#more");
const interactionTemplate = document.querySelector("#post-interactions");
const apiRoot = "/api/nyan-confessions";
const feedPath = apiRoot + "/feed";
const ownerTools = document.querySelector("#owner-tools");
const questionForm = document.querySelector("#question-form");
const questionField = document.querySelector("#question-input");
const moderationList = document.querySelector("#moderation-list");
const moderationStatus = document.querySelector("#moderation-status");
const moderationMore = document.querySelector("#moderation-more");
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
let moderationCursor = null;
let moderationLoad = 0;

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

function button(label, action) {
  const control = document.createElement("button");
  control.className = "post-action";
  control.type = "button";
  control.textContent = label;
  control.addEventListener("click", action);
  return control;
}

async function runAction(control, status, action, fallback) {
  control.disabled = true;
  status.dataset.state = "";
  status.textContent = "";
  try {
    await action();
  } catch (error) {
    status.dataset.state = "error";
    status.textContent = error.message || fallback;
  } finally {
    control.disabled = false;
  }
}

function applyQuestion(question) {
  document.querySelector("#weekly-question").hidden = !question;
  document.querySelector("#weekly-question-text").textContent = question || "";
  if (ownerHeaders) questionField.value = question || "";
}

async function loadQuestion() {
  try {
    const data = await api(apiRoot + "/question");
    applyQuestion(data.question);
  } catch {
    if (ownerHeaders) questionForm.querySelector(".status").textContent = "Не удалось загрузить вопрос недели.";
  }
}

function postLink(postId) {
  const url = new URL(location.pathname, location.origin);
  url.searchParams.set("post", postId);
  return url.href;
}

async function sharePost(postId, status) {
  const url = postLink(postId);
  try {
    if (!navigator.clipboard?.writeText) throw new Error();
    await navigator.clipboard.writeText(url);
    status.textContent = "Ссылка скопирована.";
  } catch {
    window.prompt("Скопируй ссылку на признание", url);
  }
}

function reportEntry(control, status, postId, commentId = null) {
  runAction(control, status, async () => {
    await postJson(feedPath + "/" + postId + "/report", { comment_id: commentId });
    status.textContent = "Жалоба отправлена.";
    control.hidden = true;
  }, "Не удалось отправить жалобу.");
}

function showPin(article, pinned) {
  article.querySelector(".post-pin").hidden = !pinned;
  const control = article.querySelector(".pin-post");
  control.textContent = pinned ? "Открепить" : "Закрепить";
  control.setAttribute("aria-pressed", String(pinned));
}

function reflectPin(pinnedId) {
  const ordered = [...posts.children].sort((a, b) => Number(b.id.slice(5)) - Number(a.id.slice(5)));
  for (const article of ordered) {
    const pinned = article.id === "post-" + pinnedId;
    showPin(article, pinned);
    if (pinned) posts.prepend(article);
    else posts.append(article);
  }
}

function reflectHide(postId, commentId, total) {
  const article = document.getElementById("post-" + postId);
  if (commentId === null) {
    article?.remove();
    if (!posts.childElementCount && cursor === null) {
      feedStatus.textContent = "Пока признаний нет.";
      feedStatus.hidden = false;
    }
    return;
  }
  article?.dispatchEvent(new CustomEvent("commenthidden", { detail: { commentId, total } }));
}

async function moderateEntry(action, postId, commentId = null) {
  const result = await postJson(apiRoot + "/owner/moderation",
    { post_id: postId, comment_id: commentId, action }, ownerHeaders);
  if (action === "hide") reflectHide(postId, commentId, result.total);
  if (action === "restore") {
    posts.replaceChildren();
    cursor = null;
    await loadPosts();
  }
  if (ownerTools.open) void loadModeration(true);
}

function mountPostActions(controls, post) {
  const share = controls.querySelector(".share-post");
  const report = controls.querySelector(".report-post");
  const pin = controls.querySelector(".pin-post");
  const hide = controls.querySelector(".hide-post");
  const status = controls.querySelector(".post-action-status");
  share.addEventListener("click", () => { void sharePost(post.id, status); });
  report.addEventListener("click", () => reportEntry(report, status, post.id));
  showPin(controls, post.pinned === true);
  if (!ownerHeaders) return;

  pin.hidden = false;
  hide.hidden = false;
  pin.addEventListener("click", () => runAction(pin, status, async () => {
    const result = await postJson(apiRoot + "/owner/pin",
      { post_id: post.id, pinned: pin.getAttribute("aria-pressed") !== "true" }, ownerHeaders);
    reflectPin(result.pinned_id);
  }, "Не удалось изменить закреп."));
  hide.addEventListener("click", () => runAction(hide, status,
    () => moderateEntry("hide", post.id), "Не удалось скрыть признание."));
}

function moderationEntry(entry) {
  const article = document.createElement("article");
  article.className = "post-comment";
  const meta = document.createElement("div");
  meta.className = "meta";
  const state = document.createElement("strong");
  state.textContent = entry.hidden ? "Скрыто" : "Жалоба";
  const link = document.createElement(entry.hidden ? "span" : "a");
  if (!entry.hidden) {
    link.href = postLink(entry.post_id);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  link.textContent = entry.comment_id === null ? `Признание №${entry.post_id}` : `Комментарий к №${entry.post_id}`;
  meta.append(state, link);
  const text = document.createElement("p");
  text.className = "text";
  text.textContent = entry.body;
  const actions = document.createElement("div");
  actions.className = "post-actions comment-actions";
  const status = document.createElement("p");
  status.className = "status";
  status.setAttribute("role", "status");

  function addAction(label, action) {
    const control = button(label, () => runAction(control, status,
      () => moderateEntry(action, entry.post_id, entry.comment_id), "Не удалось применить действие."));
    actions.append(control);
  }
  if (entry.hidden) addAction("Восстановить", "restore");
  else {
    addAction("Скрыть", "hide");
    addAction("Отклонить жалобу", "dismiss");
  }
  article.append(meta, text, actions, status);
  return article;
}

async function loadModeration(reset = false) {
  const request = ++moderationLoad;
  if (reset) moderationCursor = null;
  const path = apiRoot + "/owner/moderation";
  moderationMore.disabled = true;
  moderationStatus.dataset.state = "";
  moderationStatus.textContent = "Загружаем…";
  try {
    const data = await api(path + (moderationCursor === null ? "" : "?before=" + moderationCursor),
      { headers: ownerHeaders });
    if (request !== moderationLoad) return;
    if (reset) moderationList.replaceChildren();
    moderationList.append(...data.items.map(moderationEntry));
    moderationCursor = data.before;
    moderationMore.hidden = moderationCursor === null;
    moderationMore.textContent = "Показать ещё";
    moderationStatus.textContent = moderationList.childElementCount ? "" : "Жалоб и скрытых записей пока нет.";
  } catch (error) {
    if (request !== moderationLoad) return;
    moderationStatus.dataset.state = "error";
    moderationStatus.textContent = error.message || "Не удалось загрузить записи.";
    moderationMore.hidden = false;
    moderationMore.textContent = "Повторить";
  } finally {
    if (request === moderationLoad) moderationMore.disabled = false;
  }
}

function mountOwnerTools() {
  ownerTools.hidden = false;
  ownerTools.addEventListener("toggle", () => {
    if (ownerTools.open) void loadModeration(true);
  });
  moderationMore.addEventListener("click", () => {
    void loadModeration(moderationCursor === null);
  });
  questionForm.addEventListener("submit", event => {
    event.preventDefault();
    const control = questionForm.querySelector("button");
    const status = questionForm.querySelector(".status");
    void runAction(control, status, async () => {
      const data = await postJson(apiRoot + "/owner/question", { body: questionField.value }, ownerHeaders);
      applyQuestion(data.question);
      status.textContent = data.question ? "Вопрос сохранён." : "Вопрос скрыт.";
    }, "Не удалось сохранить вопрос.");
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
    if (data.owner === true) {
      ownerHeaders = headers;
      mountOwnerTools();
    }
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

function mountComments(controls, article, post, path) {
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
  let parentId = null;
  const preview = form.querySelector(".reply-preview");

  function pickReply(entry = null) {
    parentId = entry?.id ?? null;
    preview.hidden = !entry;
    preview.querySelector("p").textContent = entry ? "Ответ на: " + entry.body.slice(0, 120) : "";
    if (entry) field.focus();
  }

  preview.querySelector(".cancel-reply").addEventListener("click", () => pickReply());
  article.addEventListener("commenthidden", event => {
    const { commentId, total } = event.detail;
    document.getElementById("comment-" + commentId)?.remove();
    rendered.delete(commentId);
    if (parentId === commentId) pickReply();
    for (const quote of list.querySelectorAll(`[data-parent-id="${commentId}"]`)) {
      quote.textContent = "Комментарий скрыт.";
    }
    updateCount(total);
  });

  panel.id = "comments-" + post.id;
  toggle.setAttribute("aria-controls", panel.id);

  function updateCount(total = 0) {
    toggle.textContent = total ? `Комментарии · ${total}` : "Комментировать";
  }

  function addComment(entry, prepend = false) {
    if (rendered.has(entry.id)) return;
    rendered.add(entry.id);
    const comment = renderEntry(entry, "post-comment");
    comment.id = "comment-" + entry.id;
    if (entry.reply_to) {
      const quote = document.createElement("blockquote");
      quote.className = "reply-quote";
      quote.dataset.parentId = entry.reply_to.id;
      quote.textContent = entry.reply_to.body || "Комментарий скрыт.";
      comment.querySelector(".text").before(quote);
    }

    const actions = document.createElement("div");
    actions.className = "post-actions comment-actions";
    const report = button("Пожаловаться", () => reportEntry(report, status, post.id, entry.id));
    actions.append(button("Ответить", () => pickReply(entry)), report);
    if (ownerHeaders) {
      const hide = button("Скрыть", () => runAction(hide, status,
        () => moderateEntry("hide", post.id, entry.id), "Не удалось скрыть комментарий."));
      actions.append(hide);
    }
    comment.append(actions);
    if (prepend) list.prepend(comment);
    else list.append(comment);
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
      const data = await postJson(path, { body, reply_to: parentId });
      addComment(data.comment, true);
      updateCount(data.total);
      field.value = "";
      pickReply();
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
  const existing = document.getElementById(id);
  if (existing) return existing;
  const article = renderEntry(post, "post");
  article.id = id;
  const controls = interactionTemplate.content.cloneNode(true);
  const path = feedPath + "/" + post.id;
  mountReactions(controls, post, path);
  mountOwnerHeart(controls, post, path);
  mountComments(controls, article, post, path + "/comments");
  mountPostActions(controls, post);
  article.append(controls);

  if (prepend) {
    const pinned = [...posts.children].find(item => !item.querySelector(".post-pin").hidden);
    if (pinned && !post.pinned) pinned.after(article);
    else posts.prepend(article);
  } else {
    posts.append(article);
  }
  return article;
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
async function start() {
  await loadOwner();
  void loadQuestion();
  const postId = new URLSearchParams(location.search).get("post");
  if (/^[1-9][0-9]{0,9}$/.test(postId || "") && Number(postId) <= 2147483647) {
    try {
      const post = await api(feedPath + "/" + postId);
      const article = renderPost(post, true);
      article.querySelector(".comments-toggle").click();
      article.scrollIntoView({ block: "start" });
    } catch (error) {
      document.querySelector("#shared-status").textContent = error.message || "Не удалось открыть признание.";
    }
  }
  await loadPosts();
}
void start();
