(function () {
  "use strict";

  const vinInput = document.getElementById("vin-input");
  const decodeBtn = document.getElementById("decode-btn");
  const vinError = document.getElementById("vin-error");
  const vehicleSummary = document.getElementById("vehicle-summary");

  const requesterName = document.getElementById("requester-name");
  const requesterEmail = document.getElementById("requester-email");
  const nameError = document.getElementById("name-error");
  const emailError = document.getElementById("email-error");
  const optionsError = document.getElementById("options-error");

  const submitBtn = document.getElementById("submit-btn");
  const statusLine = document.getElementById("status-line");
  const statusText = document.getElementById("status-text");

  const resultsPanel = document.getElementById("panel-results");
  const resultsBody = document.getElementById("results-body");
  const demoBadge = document.getElementById("demo-badge");

  const historyTbody = document.getElementById("history-tbody");
  const refreshHistoryBtn = document.getElementById("refresh-history-btn");

  const BOT_CONFIGURED = !!document.querySelector(".mode-live");

  let lastDecodedVehicle = null;

  // ---------- Tabs ----------
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
      if (btn.dataset.tab === "history") loadHistory();
    });
  });

  // ---------- VIN decode ----------
  async function decodeVin() {
    const vin = vinInput.value.trim().toUpperCase();
    vinError.textContent = "";
    vehicleSummary.hidden = true;
    lastDecodedVehicle = null;

    if (vin.length !== 17) {
      vinError.textContent = "VIN must be exactly 17 characters.";
      return;
    }

    decodeBtn.disabled = true;
    decodeBtn.textContent = "Decoding…";
    try {
      const res = await fetch(`/api/decode-vin/${encodeURIComponent(vin)}`);
      const data = await res.json();
      if (!res.ok) {
        vinError.textContent = data.error || "Could not decode VIN.";
        return;
      }
      lastDecodedVehicle = data;
      document.getElementById("vs-year").textContent = data.year || "—";
      document.getElementById("vs-make").textContent = data.make || "—";
      document.getElementById("vs-model").textContent = data.model || "—";
      document.getElementById("vs-trim").textContent = data.trim || "—";
      document.getElementById("vs-body").textContent = data.body_class || "—";
      document.getElementById("vs-engine").textContent = data.engine || "—";
      document.getElementById("vs-fuel").textContent = data.fuel_type || "—";
      document.getElementById("vs-plant").textContent = data.plant_country || "—";
      vehicleSummary.hidden = false;
    } catch (err) {
      vinError.textContent = "Network error decoding VIN.";
    } finally {
      decodeBtn.disabled = false;
      decodeBtn.textContent = "Decode";
    }
  }
  decodeBtn.addEventListener("click", decodeVin);
  vinInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") decodeVin();
  });

  // ---------- Submit request ----------
  function selectedOptions() {
    return Array.from(document.querySelectorAll(".option-checkbox:checked")).map((el) => el.value);
  }

  function renderReport(vehicle, history, pdfUrl) {
    demoBadge.hidden = false;
    if (history.is_demo_data) {
      demoBadge.textContent = "Demo data";
      demoBadge.classList.remove("badge-live");
      demoBadge.classList.add("badge-demo");
    } else {
      demoBadge.textContent = "Live data (your bot)";
      demoBadge.classList.remove("badge-demo");
      demoBadge.classList.add("badge-live");
    }
    if (history.pdf_available) {
      resultsBody.innerHTML = `
        <p style="margin-top:0;color:var(--text-muted);font-size:13px;">
          ${vehicle.year || ""} ${vehicle.make || ""} ${vehicle.model || ""} ${vehicle.trim || ""} · VIN ${vehicle.vin}
        </p>
        <div class="pdf-panel">
          <span class="pdf-panel-icon">📄</span>
          <div class="pdf-panel-info">
            <h3>Carfax report ready</h3>
            <p>Real report fetched live through your connected Carfax bot.</p>
          </div>
          <a class="btn btn-primary" href="${pdfUrl}" target="_blank" rel="noopener">Open PDF</a>
        </div>
      `;
      resultsPanel.hidden = false;
      resultsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }

    const cards = [];

    if (history.accidents) {
      const a = history.accidents;
      cards.push(`
        <div class="report-card">
          <h3>Accident History</h3>
          <div class="metric">${a.count}</div>
          <ul>${a.events.map((e) => `<li>${e.date} — ${e.severity}: ${e.description}</li>`).join("") || "<li>No accidents on record.</li>"}</ul>
        </div>`);
    }
    if (history.service) {
      const s = history.service;
      cards.push(`
        <div class="report-card">
          <h3>Service Records</h3>
          <div class="metric">${s.count}</div>
          <ul>${s.records.map((r) => `<li>${r.date} @ ${r.mileage.toLocaleString()} mi — ${r.service}</li>`).join("")}</ul>
        </div>`);
    }
    if (history.ownership) {
      const o = history.ownership;
      cards.push(`
        <div class="report-card">
          <h3>Ownership History</h3>
          <div class="metric">${o.count}</div>
          <ul>${o.owners.map((ow) => `<li>Owner ${ow.owner_number}: ${ow.type}, ~${ow.estimated_length_years} yr(s)</li>`).join("")}</ul>
        </div>`);
    }
    if (history.title) {
      const t = history.title;
      cards.push(`
        <div class="report-card">
          <h3>Title &amp; Lien</h3>
          <div class="${t.status === "Clean" ? "tag-clean" : "tag-flag"}">${t.status}</div>
          <ul><li>Lien on record: ${t.lien_on_record ? "Yes" : "No"}</li></ul>
        </div>`);
    }
    if (history.odometer) {
      const od = history.odometer;
      cards.push(`
        <div class="report-card">
          <h3>Odometer</h3>
          <div class="${od.rollback_detected ? "tag-flag" : "tag-clean"}">${od.rollback_detected ? "Rollback suspected" : "No issues found"}</div>
          <ul><li>Last reported mileage: ${od.last_reported_mileage.toLocaleString()} mi</li></ul>
        </div>`);
    }

    resultsBody.innerHTML = `
      <p style="margin-top:0;color:var(--text-muted);font-size:13px;">
        ${vehicle.year || ""} ${vehicle.make || ""} ${vehicle.model || ""} ${vehicle.trim || ""} · VIN ${vehicle.vin}
      </p>
      <div class="report-grid">${cards.join("")}</div>
    `;
    resultsPanel.hidden = false;
    resultsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function submitRequest() {
    nameError.textContent = "";
    emailError.textContent = "";
    optionsError.textContent = "";
    vinError.textContent = "";

    const vin = vinInput.value.trim().toUpperCase();
    const name = requesterName.value.trim();
    const email = requesterEmail.value.trim();
    const options = selectedOptions();

    let hasError = false;
    if (vin.length !== 17) {
      vinError.textContent = "VIN must be exactly 17 characters.";
      hasError = true;
    }
    if (!name) {
      nameError.textContent = "Requester name is required.";
      hasError = true;
    }
    if (!email || !email.includes("@")) {
      emailError.textContent = "A valid email is required.";
      hasError = true;
    }
    if (options.length === 0) {
      optionsError.textContent = "Select at least one report section.";
      hasError = true;
    }
    if (hasError) return;

    submitBtn.disabled = true;
    statusLine.hidden = false;
    statusText.textContent = BOT_CONFIGURED
      ? "Requesting live report — this can take a couple of minutes…"
      : "Requesting report…";
    let keepStatusVisible = false;

    try {
      const res = await fetch("/api/request-report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vin,
          requester_name: name,
          requester_email: email,
          options,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        if (data.errors) {
          statusText.textContent = "Request failed.";
          if (data.errors.vin) vinError.textContent = data.errors.vin;
          if (data.errors.requester_name) nameError.textContent = data.errors.requester_name;
          if (data.errors.requester_email) emailError.textContent = data.errors.requester_email;
          if (data.errors.options) optionsError.textContent = data.errors.options;
        } else if (data.error) {
          // A real bot/report failure (not a field validation issue) -- keep
          // it visible in the status line rather than auto-hiding, since
          // this means the live report genuinely failed.
          statusText.textContent = data.error;
          keepStatusVisible = true;
        }
        return;
      }
      statusText.textContent = "Report ready.";
      renderReport(data.vehicle, data.history, data.pdf_url);
    } catch (err) {
      statusText.textContent = "Network error requesting report.";
      keepStatusVisible = true;
    } finally {
      submitBtn.disabled = false;
      if (!keepStatusVisible) {
        setTimeout(() => {
          statusLine.hidden = true;
        }, 2500);
      }
    }
  }
  submitBtn.addEventListener("click", submitRequest);

  // ---------- History ----------
  async function loadHistory() {
    historyTbody.innerHTML = `<tr><td colspan="11" class="empty-row">Loading…</td></tr>`;
    try {
      const res = await fetch("/api/history");
      const rows = await res.json();
      if (!rows.length) {
        historyTbody.innerHTML = `<tr><td colspan="11" class="empty-row">No requests yet.</td></tr>`;
        return;
      }
      historyTbody.innerHTML = rows
        .map(
          (r) => `
        <tr>
          <td>${r.id}</td>
          <td>${r.vin}</td>
          <td>${[r.year, r.make, r.model].filter(Boolean).join(" ")}</td>
          <td>${r.requester_name}<br><span style="color:var(--text-muted)">${r.requester_email}</span></td>
          <td>${r.options.split(",").join(", ")}</td>
          <td>${r.accident_count ?? "—"}</td>
          <td>${r.owner_count ?? "—"}</td>
          <td>${r.title_status ?? "—"}</td>
          <td>${r.data_source === "bot" ? "Live (bot)" : "Demo"}</td>
          <td>${r.pdf_filename ? `<a href="/reports/${r.pdf_filename}" target="_blank" rel="noopener">Download PDF</a>` : "—"}</td>
          <td>${new Date(r.created_at).toLocaleString()}</td>
        </tr>`
        )
        .join("");
    } catch (err) {
      historyTbody.innerHTML = `<tr><td colspan="11" class="empty-row">Could not load history.</td></tr>`;
    }
  }
  refreshHistoryBtn.addEventListener("click", loadHistory);
})();
