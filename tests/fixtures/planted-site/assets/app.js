// Tidewell Physio front-end
const API_BASE = "http://localhost:3000/api";

function loadBookings() {
  const body = document.getElementById("bookings");
  if (!body) return;
  // Bookings come from the API in production; nothing is rendered until it answers.
  fetch(API_BASE + "/bookings")
    .then((r) => r.json())
    .then((rows) => {
      for (const b of rows) {
        const tr = document.createElement("tr");
        for (const v of [b.date, b.time, b.staff, b.service, b.status]) {
          const td = document.createElement("td");
          td.textContent = v;
          tr.appendChild(td);
        }
        body.appendChild(tr);
      }
    })
    .catch(() => {});
}

function wireBooking() {
  const btn = document.getElementById("confirm-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    document.getElementById("book-status").textContent = "Checking availability…";
  });
}

wireBooking();
loadBookings();
window.analytics.track("page_view", { path: location.pathname });
