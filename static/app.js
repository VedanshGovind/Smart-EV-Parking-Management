// ChargePark - small front-end behaviour
// 1. collapsible sidebar  2. dismissible messages  3. styled dropdowns

(function () {
    // ---------- sidebar ----------
    var toggle = document.getElementById("sidebar-toggle");
    if (toggle) {
        toggle.addEventListener("click", function () {
            var collapsed = document.documentElement.classList.toggle("collapsed");
            try { localStorage.setItem("sidebar", collapsed ? "collapsed" : "open"); } catch (e) {}
        });
    }

    // ---------- messages ----------
    document.querySelectorAll(".flash-close").forEach(function (btn) {
        btn.addEventListener("click", function () { btn.parentElement.remove(); });
    });

    // ---------- dropdowns ----------
    // Every <select class="js-select"> is replaced by a styled dropdown.
    // The real select stays in the page (hidden) so the form still submits normally.
    var CHEVRON = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
    var TICK = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    var all = [];

    function el(tag, className, html) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (html !== undefined) node.innerHTML = html;
        return node;
    }

    function closeAll(except) {
        all.forEach(function (d) { if (d !== except) d.close(); });
    }

    function enhance(select) {
        var wrap = el("div", "select");
        select.parentNode.insertBefore(wrap, select);
        wrap.appendChild(select);
        select.classList.add("select-native");
        select.tabIndex = -1;

        var trigger = el("button", "select-trigger");
        trigger.type = "button";
        trigger.setAttribute("aria-haspopup", "listbox");
        trigger.setAttribute("aria-expanded", "false");
        var valueBox = el("span", "select-value");
        trigger.appendChild(valueBox);
        trigger.insertAdjacentHTML("beforeend", '<span class="select-arrow">' + CHEVRON + "</span>");
        wrap.appendChild(trigger);

        var label = select.id ? document.querySelector('label[for="' + select.id + '"]') : null;
        if (label) label.addEventListener("click", function (e) { e.preventDefault(); trigger.focus(); });

        var options = Array.prototype.slice.call(select.options);

        // nothing to choose from
        if (!options.length) {
            wrap.classList.add("is-empty");
            trigger.disabled = true;
            valueBox.innerHTML = '<span class="opt-sub">' + (select.getAttribute("data-empty") || "Nothing to select") + "</span>";
            if (select.form) {
                select.form.querySelectorAll('button[type="submit"]').forEach(function (b) { b.disabled = true; });
            }
            return;
        }

        var menu = el("ul", "select-menu");
        menu.setAttribute("role", "listbox");
        wrap.appendChild(menu);

        var items = options.map(function (opt, index) {
            var li = el("li", "option");
            li.setAttribute("role", "option");
            var text = el("span", "opt-text");
            text.appendChild(el("span", "opt-main", ""));
            text.firstChild.textContent = opt.textContent.trim();
            if (opt.getAttribute("data-sub")) {
                var sub = el("span", "opt-sub", "");
                sub.textContent = opt.getAttribute("data-sub");
                text.appendChild(sub);
            }
            li.appendChild(text);
            li.insertAdjacentHTML("beforeend", '<span class="opt-tick">' + TICK + "</span>");
            li.addEventListener("mousedown", function (e) { e.preventDefault(); });
            li.addEventListener("click", function () { choose(index); close(); trigger.focus(); });
            li.addEventListener("mousemove", function () { setActive(index); });
            menu.appendChild(li);
            return li;
        });

        var active = select.selectedIndex < 0 ? 0 : select.selectedIndex;

        function render() {
            var opt = options[select.selectedIndex < 0 ? 0 : select.selectedIndex];
            valueBox.innerHTML = "";
            var main = el("span", "opt-main"); main.textContent = opt.textContent.trim();
            valueBox.appendChild(main);
            if (opt.getAttribute("data-sub")) {
                var sub = el("span", "opt-sub"); sub.textContent = opt.getAttribute("data-sub");
                valueBox.appendChild(sub);
            }
            items.forEach(function (li, i) { li.classList.toggle("is-selected", i === select.selectedIndex); });
        }

        function setActive(i) {
            active = Math.max(0, Math.min(items.length - 1, i));
            items.forEach(function (li, n) { li.classList.toggle("is-active", n === active); });
            var li = items[active];
            if (li.offsetTop < menu.scrollTop) menu.scrollTop = li.offsetTop;
            else if (li.offsetTop + li.offsetHeight > menu.scrollTop + menu.clientHeight) {
                menu.scrollTop = li.offsetTop + li.offsetHeight - menu.clientHeight;
            }
        }

        function choose(i) {
            select.selectedIndex = i;
            render();
            select.dispatchEvent(new Event("change", { bubbles: true }));
        }

        function open() {
            closeAll(api);
            var rect = trigger.getBoundingClientRect();
            var below = window.innerHeight - rect.bottom;
            wrap.classList.toggle("up", below < 290 && rect.top > below);
            wrap.classList.add("open");
            trigger.setAttribute("aria-expanded", "true");
            setActive(select.selectedIndex < 0 ? 0 : select.selectedIndex);
        }

        function close() {
            wrap.classList.remove("open");
            trigger.setAttribute("aria-expanded", "false");
        }

        function isOpen() { return wrap.classList.contains("open"); }

        trigger.addEventListener("click", function () { isOpen() ? close() : open(); });

        trigger.addEventListener("keydown", function (e) {
            var key = e.key;
            if (key === "ArrowDown" || key === "ArrowUp") {
                e.preventDefault();
                if (!isOpen()) { open(); return; }
                setActive(active + (key === "ArrowDown" ? 1 : -1));
            } else if (key === "Enter" || key === " ") {
                e.preventDefault();
                if (isOpen()) { choose(active); close(); } else { open(); }
            } else if (key === "Escape") {
                close();
            } else if (key === "Tab") {
                close();
            } else if (key.length === 1) {
                // type a letter to jump to the first matching option
                var typed = key.toLowerCase();
                for (var n = 1; n <= items.length; n++) {
                    var idx = (active + n) % items.length;
                    if (options[idx].textContent.trim().toLowerCase().indexOf(typed) === 0) {
                        if (!isOpen()) open();
                        setActive(idx);
                        break;
                    }
                }
            }
        });

        var api = { close: close };
        all.push(api);
        render();
    }

    document.querySelectorAll("select.js-select").forEach(enhance);

    document.addEventListener("click", function (e) {
        if (!e.target.closest(".select")) closeAll();
    });
})();
