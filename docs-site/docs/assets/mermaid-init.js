/*
 * Selbst gehostetes Mermaid-Rendering, bewusst NICHT ueber den in MkDocs Material
 * eingebauten Mechanismus (der laedt mermaid.js immer von unpkg.com nach - siehe
 * mkdocs.yml). Der Fence-Output nutzt daher die Klasse "mermaid-diagram" statt
 * "mermaid", damit Material erst gar nicht versucht, selbst etwas zu laden.
 *
 * Quelltext wird bewusst direkt aus dem verschachtelten <code>-Element gelesen und
 * per mermaid.render() gerendert - NICHT ueber mermaid.run(el), da Material's
 * content.code.copy-Feature einen Kopieren-Button in jeden <pre><code>-Block
 * injiziert (auch hier) und mermaid.run() diesen Button dann faelschlich als Teil
 * des Diagrammtexts liest ("No diagram type detected").
 */
(function () {
  var thisScript = document.currentScript;
  var mermaidSrc = thisScript
    ? new URL("mermaid.min.js", thisScript.src).href
    : "assets/mermaid.min.js";

  var idCounter = 0;

  function ensureLightbox() {
    var lb = document.querySelector(".hocx-lightbox");
    if (lb) return lb;

    lb = document.createElement("div");
    lb.className = "hocx-lightbox";
    lb.hidden = true;

    var closeBtn = document.createElement("button");
    closeBtn.className = "hocx-lightbox-close";
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "Schliessen");
    closeBtn.innerHTML = "&times;";
    lb.appendChild(closeBtn);

    var content = document.createElement("div");
    content.className = "hocx-lightbox-content";
    lb.appendChild(content);

    document.body.appendChild(lb);

    function close() {
      lb.hidden = true;
      content.innerHTML = "";
    }
    lb.addEventListener("click", function (e) {
      if (e.target === lb) close();
    });
    closeBtn.addEventListener("click", close);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !lb.hidden) close();
    });

    lb._content = content;
    return lb;
  }

  function openLightbox(svgEl) {
    var lb = ensureLightbox();
    lb._content.innerHTML = "";
    var clone = svgEl.cloneNode(true);
    clone.removeAttribute("style");

    // Groesse explizit aus der viewBox berechnen: das geklonte SVG haengt sonst in
    // einem Flex-Container ohne eigene Breite und faellt auf ein winziges
    // UA-Default (~80x80px) zurueck, egal was CSS max-width/max-height sagen.
    var viewBox = svgEl.getAttribute("viewBox");
    if (viewBox) {
      var parts = viewBox.split(/\s+/).map(Number);
      var vbW = parts[2];
      var vbH = parts[3];
      if (vbW > 0 && vbH > 0) {
        var maxW = window.innerWidth - 96;
        var maxH = window.innerHeight - 96;
        var scale = Math.min(maxW / vbW, maxH / vbH);
        clone.setAttribute("width", Math.round(vbW * scale));
        clone.setAttribute("height", Math.round(vbH * scale));
      }
    }

    lb._content.appendChild(clone);
    lb.hidden = false;
  }

  function loadMermaid() {
    if (typeof mermaid !== "undefined") return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = mermaidSrc;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  function renderAll(nodes) {
    return loadMermaid().then(function () {
      var scheme = document.body.getAttribute("data-md-color-scheme");
      mermaid.initialize({
        startOnLoad: false,
        theme: scheme === "slate" ? "dark" : "default",
        securityLevel: "loose",
        fontFamily: "Inter, sans-serif",
      });

      nodes.forEach(function (el) {
        var codeEl = el.querySelector("code") || el;
        // Bei einem Re-Render (Theme-Wechsel) steht der Quelltext nicht mehr im
        // <code>-Element (das wurde beim ersten Render schon durch das SVG ersetzt)
        // - dann den Originaltext aus data-hocx-source verwenden.
        var source = codeEl ? codeEl.textContent : el.getAttribute("data-hocx-source");
        if (!el.hasAttribute("data-hocx-source")) {
          el.setAttribute("data-hocx-source", source);
        } else {
          source = el.getAttribute("data-hocx-source");
        }
        var id = "hocx-mermaid-" + idCounter++;
        mermaid
          .render(id, source)
          .then(function (result) {
            el.innerHTML = result.svg;
            el.setAttribute("data-hocx-rendered", "true");
            el.title = "Für Vollbild anklicken";
            var svg = el.querySelector("svg");
            el.onclick = function () {
              if (svg) openLightbox(svg);
            };
          })
          .catch(function (err) {
            console.error("hocX-Doku: Mermaid-Rendering fehlgeschlagen:", err);
          });
      });
    });
  }

  document$.subscribe(function () {
    var nodes = document.querySelectorAll(".mermaid-diagram:not([data-hocx-rendered])");
    if (nodes.length) renderAll(nodes);
  });

  // Beim manuellen Umschalten des Hell-/Dunkel-Reglers bereits gerenderte
  // Diagramme im neuen Theme neu zeichnen.
  var observer = new MutationObserver(function () {
    var rendered = document.querySelectorAll(".mermaid-diagram[data-hocx-rendered]");
    if (rendered.length) {
      rendered.forEach(function (el) { el.removeAttribute("data-hocx-rendered"); });
      renderAll(rendered);
    }
  });
  observer.observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
})();
