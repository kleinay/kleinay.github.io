/* Renders a post JSON into the page: markdown -> HTML, then KaTeX over the result.
   Math is pulled out before the markdown pass, because marked would otherwise eat
   underscores and backslashes inside $...$ before KaTeX ever sees them. The
   placeholders carry no surrounding spaces, since marked trims paragraph edges. */

(function () {
  "use strict";

  var ROOT = "/notes-24ddee3338";

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmtDate(iso) {
    var d = new Date(iso + "T00:00:00");
    if (isNaN(d)) return iso;
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  }

  /* --- math shielding ------------------------------------------------ */

  function stashMath(md) {
    var store = [];
    function keep(tex, display) {
      store.push({ tex: tex, display: display });
      return "@@MATH" + (store.length - 1) + "@@";
    }
    // Fenced and inline code first, so a $ inside code is left alone.
    var code = [];
    md = md.replace(/```[\s\S]*?```|`[^`\n]*`/g, function (m) {
      code.push(m);
      return "@@CODE" + (code.length - 1) + "@@";
    });
    md = md.replace(/\$\$([\s\S]+?)\$\$/g, function (_, tex) { return keep(tex, true); });
    md = md.replace(/\$([^\$\n]+?)\$/g, function (_, tex) { return keep(tex, false); });
    md = md.replace(/@@CODE(\d+)@@/g, function (_, i) { return code[+i]; });
    return { md: md, store: store };
  }

  function renderMath(html, store) {
    return html.replace(/@@MATH(\d+)@@/g, function (_, i) {
      var item = store[+i];
      try {
        return katex.renderToString(item.tex, {
          displayMode: item.display,
          throwOnError: false,
          strict: false,
        });
      } catch (e) {
        return "<code>" + esc(item.tex) + "</code>";
      }
    });
  }

  /* --- markdown ------------------------------------------------------ */

  function toHtml(md) {
    var shielded = stashMath(md);
    marked.setOptions({ gfm: true, breaks: false, mangle: false, headerIds: false });
    return renderMath(marked.parse(shielded.md), shielded.store);
  }

  function decorate(article) {
    // Wide tables scroll inside their own box rather than shifting the page.
    article.querySelectorAll("table").forEach(function (t) {
      var box = document.createElement("div");
      box.className = "table-scroll";
      t.parentNode.insertBefore(box, t);
      box.appendChild(t);
    });
    if (window.hljs) {
      article.querySelectorAll("pre code").forEach(function (b) {
        try { hljs.highlightElement(b); } catch (e) { /* leave it unhighlighted */ }
      });
    }
    article.querySelectorAll('a[href^="http"]').forEach(function (a) {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    });
  }

  function fetchJson(path) {
    return fetch(ROOT + path, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  /* --- pages --------------------------------------------------------- */

  function renderPost(slug) {
    var mount = document.getElementById("post");
    fetchJson("/posts/" + encodeURIComponent(slug) + ".json")
      .then(function (post) {
        document.title = post.title;
        var meta = [fmtDate(post.date), post.byline].filter(Boolean).join(" · ");
        mount.innerHTML =
          '<p class="post-date">' + esc(meta) + "</p>" +
          "<h1>" + esc(post.title) + "</h1>" +
          '<div class="body"></div>';
        var body = mount.querySelector(".body");
        body.innerHTML = toHtml(post.body);
        decorate(body);
      })
      .catch(function (e) {
        mount.innerHTML = '<p class="error">Could not load this note (' + esc(e.message) + ").</p>";
      });
  }

  function renderIndex() {
    var mount = document.getElementById("list");
    fetchJson("/posts.json")
      .then(function (posts) {
        if (!posts.length) {
          mount.innerHTML = '<p class="loading">No notes yet.</p>';
          return;
        }
        mount.innerHTML =
          '<ol class="posts">' +
          posts
            .map(function (p) {
              return (
                "<li>" +
                '<div class="post-date">' + esc(fmtDate(p.date)) + "</div>" +
                '<h2><a href="' + ROOT + "/p/" + esc(p.slug) + '/">' + esc(p.title) + "</a></h2>" +
                "<p>" + esc(p.summary) + "</p>" +
                (p.byline ? '<div class="byline">' + esc(p.byline) + "</div>" : "") +
                "</li>"
              );
            })
            .join("") +
          "</ol>";
      })
      .catch(function (e) {
        mount.innerHTML = '<p class="error">Could not load the index (' + esc(e.message) + ").</p>";
      });
  }

  window.Notes = { renderPost: renderPost, renderIndex: renderIndex };
})();
