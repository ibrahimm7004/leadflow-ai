import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AnimatePresence, motion } from "framer-motion";
import {
  Bell,
  CalendarDays,
  Check,
  Clock3,
  Database,
  Download,
  ExternalLink,
  Eye,
  Filter,
  Flame,
  Globe2,
  Loader2,
  Mail,
  MailPlus,
  MapPin,
  Phone,
  RefreshCw,
  Search,
  Settings,
  Sparkles,
  Star,
  Users,
  X,
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const DEFAULT_COLUMNS = [
  "name",
  "bestEmail",
  "phone",
  "address",
  "websiteUrl",
  "rating",
  "userRatingCount",
  "googleMapsUri",
];

const COLUMN_OPTIONS = [
  ["name", "Business"],
  ["bestEmail", "Best email"],
  ["phone", "Phone"],
  ["address", "Address"],
  ["websiteUrl", "Website"],
  ["rating", "Rating"],
  ["userRatingCount", "Reviews"],
  ["googleMapsUri", "Maps"],
  ["searchQuery", "Search"],
  ["leadDate", "Date"],
  ["emailSelectionMethod", "Email method"],
  ["emailCandidateCount", "Email candidates"],
];

const DEFAULT_SEARCH = {
  businessType: "barber",
  location: "Boston, MA",
  numLeads: 25,
  searchMode: "all_businesses",
  minRating: 3.5,
  maxUserReviews: 300,
  enabled: true,
};

function normalizeSearchConfig(value = {}, fallback = DEFAULT_SEARCH) {
  return {
    ...fallback,
    ...Object.fromEntries(Object.entries(value || {}).filter(([, item]) => item !== undefined && item !== null)),
  };
}

function localDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateFromKey(key) {
  const [year, month, day] = String(key).split("-").map(Number);
  return new Date(year, month - 1, day);
}

function monthLabel(date) {
  return date.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function calendarCells(monthDate) {
  const first = new Date(monthDate.getFullYear(), monthDate.getMonth(), 1);
  const mondayOffset = (first.getDay() + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayOffset);
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    return day;
  });
}

function api(path, options = {}) {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  }).then(async (response) => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Request failed.");
    return data;
  });
}

function cls(...values) {
  return values.filter(Boolean).join(" ");
}

function formatDate(value) {
  if (!value) return "";
  return String(value).slice(0, 10);
}

function displayValue(row, key) {
  if (key === "bestEmail") return row.bestEmail || "Not enriched";
  if (key === "websiteUrl") return row.websiteUrl || (row.hasExternalWebsite === "true" ? "External platform" : "None");
  if (key === "googleMapsUri") return row.googleMapsUri ? "Open map" : "None";
  if (key === "rating") return row.rating ? `${row.rating}` : "No rating";
  if (key === "userRatingCount") return row.userRatingCount ?? "0";
  return row[key] ?? "";
}

function hrefFor(row, key) {
  const value = row[key];
  if (!value) return "";
  if (key === "bestEmail") return `mailto:${value}`;
  if (["websiteUrl", "googleMapsUri", "bestEmailSourceUrl"].includes(key)) return value;
  return "";
}

function downloadBlob(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function exportHeaders(rows) {
  return Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
}

function exportValue(value) {
  return value === null || value === undefined ? "" : typeof value === "object" ? JSON.stringify(value) : String(value);
}

function csvEscape(value) {
  const raw = exportValue(value);
  return /[",\n\r]/.test(raw) ? `"${raw.replaceAll('"', '""')}"` : raw;
}

function sqlEscape(value) {
  return exportValue(value).replaceAll("'", "''");
}

function exportBaseName() {
  return `leads-${new Date().toISOString().slice(0, 10)}`;
}

function downloadCsv(rows) {
  const headers = exportHeaders(rows);
  const csv = [headers.join(","), ...rows.map((row) => headers.map((key) => csvEscape(row[key])).join(","))].join("\n");
  downloadBlob(`${exportBaseName()}.csv`, csv, "text/csv;charset=utf-8");
}

function downloadJson(rows) {
  downloadBlob(`${exportBaseName()}.json`, JSON.stringify(rows, null, 2), "application/json;charset=utf-8");
}

function downloadTxt(rows) {
  const headers = exportHeaders(rows);
  const txt = rows.map((row, index) => [`Lead ${index + 1}`, ...headers.map((key) => `${key}: ${exportValue(row[key])}`)].join("\n")).join("\n\n");
  downloadBlob(`${exportBaseName()}.txt`, txt, "text/plain;charset=utf-8");
}

function downloadSql(rows) {
  const headers = exportHeaders(rows);
  const values = rows.map((row) => `(${headers.map((key) => `'${sqlEscape(row[key])}'`).join(", ")})`);
  const sql = [
    `create table if not exists exported_leads (${headers.map((key) => `"${key}" text`).join(", ")});`,
    `insert into exported_leads (${headers.map((key) => `"${key}"`).join(", ")}) values`,
    `${values.join(",\n")};`,
  ].join("\n");
  downloadBlob(`${exportBaseName()}.sql`, sql, "application/sql;charset=utf-8");
}

function excelCell(value) {
  return exportValue(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function downloadExcel(rows) {
  const headers = exportHeaders(rows);
  const xml = `<?xml version="1.0"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Worksheet ss:Name="Leads">
  <Table>
   <Row>${headers.map((key) => `<Cell><Data ss:Type="String">${excelCell(key)}</Data></Cell>`).join("")}</Row>
   ${rows.map((row) => `<Row>${headers.map((key) => `<Cell><Data ss:Type="String">${excelCell(row[key])}</Data></Cell>`).join("")}</Row>`).join("")}
  </Table>
 </Worksheet>
</Workbook>`;
  downloadBlob(`${exportBaseName()}.xls`, xml, "application/vnd.ms-excel");
}

function Metric({ label, value, tone = "" }) {
  return (
    <div className={cls("metric", tone)}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SetupNotice({ bootstrap }) {
  if (bootstrap?.hostedDb?.configured && !bootstrap?.setupError) return null;
  return (
    <section className="setup-strip">
      <Database size={20} />
      <div>
        <strong>Supabase is not fully connected</strong>
        <p>
          Run `supabase_schema.sql` in Supabase, then add `SUPABASE_URL` and
          `SUPABASE_SERVICE_ROLE_KEY` to `.env`. The app UI is ready, but hosted
          leads need those settings.
        </p>
        {bootstrap?.setupError && <small>{bootstrap.setupError}</small>}
      </div>
    </section>
  );
}

function LeadRow({ row, visibleColumns, onTick, onDebug }) {
  const email = row.bestEmail || "";
  const website = row.websiteUrl || "";
  const externalWebsite = row.hasExternalWebsite === "true" ? row.externalWebsiteUrl : "";
  const phone = row.phone || "";
  const address = row.address || row.searchQuery || "";
  const displayWebsite = website || externalWebsite || "";
  const compactAddress = address.replace(", USA", "");

  return (
    <motion.article
      layout
      className={cls("lead-card", row.ticked && "is-ticked")}
      initial={{ opacity: 0, y: 10, scale: 0.99 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.99 }}
      whileHover={{ y: -2 }}
      transition={{ type: "spring", stiffness: 380, damping: 34 }}
    >
      <div className="lead-card-accent" />
      <div className="lead-card-top">
        <button className="tick-button" onClick={() => onTick(row)} aria-label={row.ticked ? "Reactivate lead" : "Tick off lead"}>
          {row.ticked ? <Check size={18} /> : <span />}
        </button>
        <div className="lead-identity">
          <div className="lead-kicker">
            <span>{row.businessType || "Lead"}</span>
            <span>{formatDate(row.leadDate)}</span>
          </div>
          <h3>{row.name || "Unnamed business"}</h3>
          <p>
            <MapPin size={14} />
            <span>{compactAddress || "No address available"}</span>
          </p>
        </div>
        <div className="lead-score-stack">
          <div>
            <Star size={15} />
            <strong>{row.rating || "0"}</strong>
            <span>stars</span>
          </div>
          <div>
            <Users size={15} />
            <strong>{row.userRatingCount || 0}</strong>
            <span>reviews</span>
          </div>
        </div>
      </div>

      <div className="lead-card-body">
        <div className={cls("lead-contact-panel", email && "has-email")}>
          <div className="panel-icon">
            <Mail size={18} />
          </div>
          <div>
            <small>Best email</small>
            {email ? <a href={`mailto:${email}`}>{email}</a> : <span>Not enriched yet</span>}
            {row.emailSelectionMethod && <em>{row.emailSelectionMethod.replaceAll("_", " ")}</em>}
          </div>
        </div>

        <div className="lead-contact-panel">
          <div className="panel-icon">
            <Phone size={18} />
          </div>
          <div>
            <small>Phone</small>
            {phone ? <a href={`tel:${phone}`}>{phone}</a> : <span>No phone listed</span>}
          </div>
        </div>

        <div className="lead-contact-panel website-panel">
          <div className="panel-icon">
            <Globe2 size={18} />
          </div>
          <div>
            <small>{website ? "Website" : externalWebsite ? "External platform" : "Website"}</small>
            {displayWebsite ? (
              <a href={displayWebsite} target="_blank" rel="noreferrer">
                {displayWebsite.replace(/^https?:\/\//, "").replace(/\/$/, "")}
              </a>
            ) : (
              <span>No website listed</span>
            )}
          </div>
        </div>
      </div>

      <div className="lead-card-footer">
        <div className="lead-context">
          <span>{row.searchQuery || `${row.businessType || "business"} in ${row.searchLocation || "selected market"}`}</span>
          {row.ticked && <strong>Reached out</strong>}
          {!row.ticked && !email && <strong>Needs enrichment</strong>}
          {!row.ticked && email && <strong className="ready">Ready</strong>}
        </div>
        <div className="lead-actions">
          {row.googleMapsUri && (
            <a className="action-button" href={row.googleMapsUri} target="_blank" rel="noreferrer">
              <ExternalLink size={16} />
              Map
            </a>
          )}
          <button className="debug-link" onClick={() => onDebug(row)}>
            <Eye size={16} />
            Details
          </button>
        </div>
      </div>
    </motion.article>
  );
}

function DebugPanel({ row, onClose }) {
  if (!row) return null;
  const debug = row.emailDebugJson || {};
  return (
    <motion.div className="drawer-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <motion.aside className="debug-drawer" initial={{ x: 420 }} animate={{ x: 0 }} exit={{ x: 420 }}>
        <header>
          <div>
            <span>Lead details</span>
            <h2>{row.name}</h2>
          </div>
          <button onClick={onClose} aria-label="Close details">
            <X size={20} />
          </button>
        </header>
        <section>
          <h3>Email outcome</h3>
          <dl>
            <dt>Best email</dt>
            <dd>{row.bestEmail || "None"}</dd>
            <dt>Status</dt>
            <dd>{row.emailScrapeStatus || "Not enriched"}</dd>
            <dt>Method</dt>
            <dd>{row.emailSelectionMethod || "None"}</dd>
            <dt>Candidates</dt>
            <dd>{row.emailCandidateCount || 0}</dd>
            <dt>Pages fetched</dt>
            <dd>{row.emailPagesFetched || 0}</dd>
            <dt>Source</dt>
            <dd>{row.bestEmailSourceUrl || "None"}</dd>
          </dl>
        </section>
        <section>
          <h3>Business</h3>
          <dl>
            <dt>Website</dt>
            <dd>{row.websiteUrl || row.externalWebsiteUrl || "None"}</dd>
            <dt>Maps</dt>
            <dd>{row.googleMapsUri || "None"}</dd>
            <dt>Search</dt>
            <dd>{row.searchQuery || "None"}</dd>
          </dl>
        </section>
        <section>
          <h3>Scrape / AI Debug</h3>
          <pre>{JSON.stringify(debug, null, 2) || "{}"}</pre>
        </section>
      </motion.aside>
    </motion.div>
  );
}

function SearchConfigFields({ value, onChange, compact = false }) {
  const set = (key, nextValue) => onChange({ ...value, [key]: nextValue });
  return (
    <div className={cls("search-config-fields", compact && "is-compact")}>
      <label>
        <span>Business type</span>
        <input value={value.businessType || ""} onChange={(event) => set("businessType", event.target.value)} placeholder="barber" />
      </label>
      <label>
        <span>Location</span>
        <input value={value.location || ""} onChange={(event) => set("location", event.target.value)} placeholder="Boston, MA" />
      </label>
      <label>
        <span>Num leads</span>
        <input type="number" min="1" max="1000" value={value.numLeads ?? 25} onChange={(event) => set("numLeads", Number(event.target.value))} />
      </label>
      <label>
        <span>Search mode</span>
        <select value={value.searchMode || "all_businesses"} onChange={(event) => set("searchMode", event.target.value)}>
          <option value="all_businesses">All businesses</option>
          <option value="qualified_no_website">No owned website</option>
        </select>
      </label>
      <label>
        <span>Min rating</span>
        <input value={value.minRating ?? 3.5} onChange={(event) => set("minRating", event.target.value)} />
      </label>
      <label>
        <span>Max reviews</span>
        <input value={value.maxUserReviews ?? 300} onChange={(event) => set("maxUserReviews", event.target.value)} />
      </label>
    </div>
  );
}

function SelectedDayEditor({ dateKey, config, inherited, onChange, onClose, onClear }) {
  const date = dateFromKey(dateKey);
  return (
    <motion.div className="calendar-popover-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <motion.aside className="calendar-popover" initial={{ opacity: 0, y: 18, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 18, scale: 0.98 }}>
        <header>
          <div>
            <span>{date.toLocaleDateString(undefined, { weekday: "long" })}</span>
            <h2>{date.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" })}</h2>
          </div>
          <button onClick={onClose} aria-label="Close day editor">
            <X size={20} />
          </button>
        </header>
        <div className="day-toggle-row">
          <button className={config.enabled ? "toggle is-on" : "toggle"} onClick={() => onChange({ ...config, enabled: !config.enabled })}>
            {config.enabled ? "Search enabled" : "Search off"}
          </button>
          {inherited ? <span>Inheriting defaults</span> : <span>Custom override</span>}
        </div>
        <SearchConfigFields value={config} onChange={onChange} />
        <footer>
          <button onClick={onClear} disabled={inherited}>Clear override</button>
          <button className="dark" onClick={onClose}>
            <Check size={18} />
            Done
          </button>
        </footer>
      </motion.aside>
    </motion.div>
  );
}

function DefaultSearchEditor({ config, weekendsOff, onChange, onKeepWeekendsOff, onAllowWeekends, onClose }) {
  return (
    <motion.div className="calendar-popover-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <motion.aside className="calendar-popover default-search-popover" initial={{ opacity: 0, y: 18, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 18, scale: 0.98 }}>
        <header>
          <div>
            <span>Default search</span>
            <h2>{config.businessType} in {config.location}</h2>
          </div>
          <button onClick={onClose} aria-label="Close default search editor">
            <X size={20} />
          </button>
        </header>
        <div className="day-toggle-row">
          <button className={config.enabled ? "toggle is-on" : "toggle"} onClick={() => onChange({ ...config, enabled: !config.enabled })}>
            {config.enabled ? "Search enabled" : "Search off"}
          </button>
          <span>{weekendsOff ? "Weekends off by default" : "Weekends allowed"}</span>
        </div>
        <div className="default-stats">
          <span>{config.numLeads} leads</span>
          <span>{config.minRating}+ stars</span>
          <span>{config.maxUserReviews} max reviews</span>
        </div>
        <SearchConfigFields value={config} onChange={onChange} />
        <div className="quick-actions">
          <button className={weekendsOff ? "is-selected" : ""} onClick={onKeepWeekendsOff}>Keep weekends off</button>
          <button className={!weekendsOff ? "is-selected" : ""} onClick={onAllowWeekends}>Allow weekends</button>
        </div>
        <footer>
          <span className="popover-note">Applies to every unedited day.</span>
          <button className="dark" onClick={onClose}>
            <Check size={18} />
            Done
          </button>
        </footer>
      </motion.aside>
    </motion.div>
  );
}

function TodayPage({ bootstrap, settings, setSettings }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("ai_decision");
  const [enriching, setEnriching] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0, found: 0, ai: 0, pages: 0 });
  const [debugRow, setDebugRow] = useState(null);
  const [runSummary, setRunSummary] = useState(bootstrap?.latestRun || {});
  const visibleColumns = settings.visibleColumns?.length ? settings.visibleColumns : DEFAULT_COLUMNS;

  const loadToday = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api("/api/app/leads/today");
      setRows(data.rows || []);
      setRunSummary(data.runSummary || {});
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (bootstrap?.hostedDb?.configured) loadToday();
    else setLoading(false);
  }, [bootstrap?.hostedDb?.configured]);

  useEffect(() => {
    if (bootstrap?.latestRun) {
      setRunSummary(bootstrap.latestRun);
    }
  }, [bootstrap?.latestRun]);

  const sortedRows = useMemo(
    () => [...rows].sort((a, b) => Number(a.ticked) - Number(b.ticked) || Number(a.userRatingCount || 0) - Number(b.userRatingCount || 0)),
    [rows],
  );
  const active = rows.filter((row) => !row.ticked);
  const emailed = rows.filter((row) => row.bestEmail).length;

  const updateRow = (updated) => {
    setRows((current) => current.map((row) => (row.id === updated.id ? updated : row)));
  };

  const tickLead = async (row) => {
    const optimistic = { ...row, ticked: !row.ticked, tickedAt: !row.ticked ? new Date().toISOString() : "" };
    updateRow(optimistic);
    try {
      const data = await api(`/api/app/leads/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ticked: !row.ticked }),
      });
      updateRow(data.row);
    } catch (err) {
      updateRow(row);
      setError(err.message);
    }
  };

  const runDailyNow = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api("/api/app/run-daily", { method: "POST", body: JSON.stringify({ notify: false }) });
      setRunSummary(data.runSummary || {});
      await loadToday();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  const enrichToday = async () => {
    const targets = rows.filter((row) => !row.ticked);
    setEnriching(true);
    setProgress({ done: 0, total: targets.length, found: 0, ai: 0, pages: 0 });
    setError("");
    for (const row of targets) {
      try {
        const data = await api(`/api/app/leads/${row.id}/enrich`, {
          method: "POST",
          body: JSON.stringify({
            enrichmentMode: mode,
            maxOpenAiCalls: mode === "local_only" ? 0 : 1,
            maxPagesPerBusiness: 100,
            maxDepth: 5,
            storeResults: true,
          }),
        });
        updateRow(data.row);
        setProgress((current) => ({
          done: current.done + 1,
          total: current.total,
          found: current.found + (data.row.bestEmail ? 1 : 0),
          ai: current.ai + (data.meta?.openAiCalls || 0),
          pages: current.pages + (data.meta?.pagesFetched || 0),
        }));
      } catch (err) {
        setError(err.message);
        setProgress((current) => ({ ...current, done: current.done + 1 }));
      }
    }
    setEnriching(false);
  };

  return (
    <motion.main className="page" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
      <SetupNotice bootstrap={bootstrap} />
      <section className="hero-workspace">
        <div>
          <p className="eyebrow">Today's Leads</p>
          <h1>Today's outreach queue.</h1>
          <p className="hero-subcopy">Daily Places results land here at 5 AM EST, sorted by lower review counts so the most likely website-upgrade opportunities stay near the top.</p>
        </div>
        <div className="hero-actions">
          <button onClick={loadToday} disabled={loading || !bootstrap?.hostedDb?.configured}>
            {loading ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
            Refresh
          </button>
          <button className="dark" onClick={runDailyNow} disabled={loading || !bootstrap?.hostedDb?.configured}>
            <Flame size={18} />
            Run now
          </button>
        </div>
      </section>

      <section className="metrics-grid">
        <Metric label="Active" value={active.length} tone="hot" />
        <Metric label="Ticked" value={rows.length - active.length} />
        <Metric label="Emails found" value={`${emailed}/${rows.length}`} />
        <Metric label="Today" value={bootstrap?.today || new Date().toISOString().slice(0, 10)} />
      </section>

      {!!runSummary?.query && (
        <section className="run-summary-band">
          <div>
            <span>Latest run</span>
            <strong>{runSummary.query}</strong>
          </div>
          <div>
            <span>Duplicates removed</span>
            <strong>{runSummary.duplicatesRemoved || 0}</strong>
          </div>
          <div>
            <span>Page depth</span>
            <strong>{`${runSummary.resumeFromPage || 1}-${runSummary.deepestPageReached || 0}`}</strong>
          </div>
          <div>
            <span>Deepest reached</span>
            <strong>{runSummary.deepestHistoricalPage || 0}</strong>
          </div>
        </section>
      )}

      <section className="control-band">
        <div>
          <span>Email enrichment</span>
          <strong>Run only when you need contact emails</strong>
        </div>
        <div className="segmented">
          <button className={mode === "local_only" ? "is-selected" : ""} onClick={() => setMode("local_only")}>Local</button>
          <button className={mode === "ai_decision" ? "is-selected" : ""} onClick={() => setMode("ai_decision")}>AI + local</button>
          <button className={mode === "gpt_web_search" ? "is-selected" : ""} onClick={() => setMode("gpt_web_search")}>Web search</button>
        </div>
        <button className="enrich-cta" onClick={enrichToday} disabled={enriching || !active.length}>
          {enriching ? <Loader2 className="spin" size={18} /> : <MailPlus size={18} />}
          {enriching ? `${progress.done}/${progress.total}` : "Enrich active leads"}
        </button>
      </section>

      {enriching && (
        <section className="progress-rail">
          <div style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }} />
          <span>{progress.found} emails found · {progress.ai} AI calls · {progress.pages} pages scraped</span>
        </section>
      )}

      {error && <p className="error-line">{error}</p>}

      <section className="lead-list">
        <AnimatePresence>
          {sortedRows.map((row) => (
            <LeadRow key={row.id} row={row} visibleColumns={visibleColumns} onTick={tickLead} onDebug={setDebugRow} />
          ))}
        </AnimatePresence>
        {!loading && !sortedRows.length && (
          <div className="empty-state">
            <Clock3 size={28} />
            <strong>No leads for today yet</strong>
            <p>Use Run now to fetch today&apos;s leads, or wait for the 5 AM automation.</p>
          </div>
        )}
      </section>
      <AnimatePresence>
        {debugRow && <DebugPanel row={debugRow} onClose={() => setDebugRow(null)} />}
      </AnimatePresence>
    </motion.main>
  );
}

function AllLeadsPage({ settings }) {
  const [rows, setRows] = useState([]);
  const [filters, setFilters] = useState({ q: "", dateFrom: "", dateTo: "", ticked: "", hasEmail: "", minRating: "", maxReviews: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [debugRow, setDebugRow] = useState(null);
  const [downloadOpen, setDownloadOpen] = useState(false);
  const visibleColumns = settings.visibleColumns?.length ? settings.visibleColumns : DEFAULT_COLUMNS;
  const activeCount = rows.filter((row) => !row.ticked).length;
  const tickedCount = rows.length - activeCount;
  const emailCount = rows.filter((row) => row.bestEmail).length;

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
      const data = await api(`/api/app/leads?${params.toString()}`);
      setRows(data.rows || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const set = (key, value) => setFilters((current) => ({ ...current, [key]: value }));

  const tickLead = async (row) => {
    const nextTicked = !row.ticked;
    setRows((current) =>
      current.map((item) =>
        item.id === row.id
          ? { ...item, ticked: nextTicked, tickedAt: nextTicked ? new Date().toISOString() : "" }
          : item,
      ),
    );
    try {
      const data = await api(`/api/app/leads/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ticked: nextTicked }),
      });
      setRows((current) => current.map((item) => (item.id === row.id ? data.row : item)));
    } catch (err) {
      setError(err.message);
      setRows((current) => current.map((item) => (item.id === row.id ? row : item)));
    }
  };

  return (
    <motion.main className="page" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
      <section className="archive-hero">
        <div>
          <p className="eyebrow">All Leads</p>
          <h1>Lead archive.</h1>
          <p className="hero-subcopy">Search by business, date, status, or enrichment state. The archive stays compact while the cards handle the detailed display.</p>
        </div>
        <div className="archive-hero-actions">
          <button onClick={load} disabled={loading}>
            {loading ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
            Refresh
          </button>
          <div className="download-menu-wrap">
            <button className="dark" onClick={() => setDownloadOpen((current) => !current)} disabled={!rows.length}>
              <Download size={18} />
              Download
            </button>
            <AnimatePresence>
              {downloadOpen && (
                <motion.div className="download-menu" initial={{ opacity: 0, y: 10, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 10, scale: 0.98 }}>
                  <button onClick={() => { downloadCsv(rows); setDownloadOpen(false); }}>CSV</button>
                  <button onClick={() => { downloadExcel(rows); setDownloadOpen(false); }}>Excel</button>
                  <button onClick={() => { downloadJson(rows); setDownloadOpen(false); }}>JSON</button>
                  <button onClick={() => { downloadTxt(rows); setDownloadOpen(false); }}>TXT</button>
                  <button onClick={() => { downloadSql(rows); setDownloadOpen(false); }}>SQL</button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </section>

      <section className="archive-stats">
        <Metric label="Total" value={rows.length} />
        <Metric label="Active" value={activeCount} tone="hot" />
        <Metric label="Ticked" value={tickedCount} />
        <Metric label="Emails" value={emailCount} />
      </section>

      <section className="archive-filter-panel">
        <div className="archive-filter-row archive-filter-row-main">
          <label className="archive-search">
            <span>Search</span>
            <input value={filters.q} onChange={(event) => set("q", event.target.value)} placeholder="business, address, email" />
          </label>
          <label>
            <span>From</span>
            <input type="date" value={filters.dateFrom} onChange={(event) => set("dateFrom", event.target.value)} />
          </label>
          <label>
            <span>To</span>
            <input type="date" value={filters.dateTo} onChange={(event) => set("dateTo", event.target.value)} />
          </label>
          <div className="archive-actions-inline">
            <button className="dark" onClick={load}>
              {loading ? <Loader2 className="spin" size={18} /> : <Filter size={18} />}
              Apply
            </button>
          </div>
        </div>
        <div className="archive-filter-row archive-filter-row-secondary">
          <label>
            <span>Status</span>
            <select value={filters.ticked} onChange={(event) => set("ticked", event.target.value)}>
              <option value="">Any</option>
              <option value="false">Active</option>
              <option value="true">Ticked</option>
            </select>
          </label>
          <label>
            <span>Email</span>
            <select value={filters.hasEmail} onChange={(event) => set("hasEmail", event.target.value)}>
              <option value="">Any</option>
              <option value="true">Has email</option>
              <option value="false">No email</option>
            </select>
          </label>
          <label>
            <span>Min rating</span>
            <input value={filters.minRating} onChange={(event) => set("minRating", event.target.value)} placeholder="3.5" />
          </label>
          <label>
            <span>Max reviews</span>
            <input value={filters.maxReviews} onChange={(event) => set("maxReviews", event.target.value)} placeholder="300" />
          </label>
        </div>
      </section>

      {error && <p className="error-line">{error}</p>}
      <section className="lead-list">
        {rows.map((row) => (
          <LeadRow key={row.id} row={row} visibleColumns={visibleColumns} onTick={tickLead} onDebug={setDebugRow} />
        ))}
      </section>
      <AnimatePresence>
        {debugRow && <DebugPanel row={debugRow} onClose={() => setDebugRow(null)} />}
      </AnimatePresence>
    </motion.main>
  );
}

function SettingsPage({ settings, setSettings }) {
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [calendarMonth, setCalendarMonth] = useState(new Date());
  const [selectedDate, setSelectedDate] = useState("");
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [defaultEditorOpen, setDefaultEditorOpen] = useState(false);
  const defaultSearch = normalizeSearchConfig(settings.defaultSearch || DEFAULT_SEARCH);
  const overrides = settings.calendarOverrides && typeof settings.calendarOverrides === "object" ? settings.calendarOverrides : {};

  const saveAll = async () => {
    setSaving(true);
    setMessage("");
    try {
      const settingsResponse = await api("/api/app/settings", {
        method: "PUT",
        body: JSON.stringify({ settings }),
      });
      setSettings(settingsResponse.settings);
      setMessage("Saved.");
    } catch (err) {
      setMessage(err.message);
    } finally {
      setSaving(false);
    }
  };

  const toggleColumn = (column) => {
    const current = settings.visibleColumns || DEFAULT_COLUMNS;
    const next = current.includes(column) ? current.filter((item) => item !== column) : [...current, column];
    setSettings({ ...settings, visibleColumns: next });
  };

  const setDefaultSearch = (next) => {
    setSettings({ ...settings, defaultSearch: normalizeSearchConfig(next) });
  };

  const configForDate = (dateKey) => {
    const date = dateFromKey(dateKey);
    const hasOverride = Boolean(overrides[dateKey]);
    const config = normalizeSearchConfig(hasOverride ? overrides[dateKey] : {}, defaultSearch);
    if (settings.weekendsOff && date.getDay() % 6 === 0 && !hasOverride) {
      config.enabled = false;
    }
    return config;
  };

  const setDateOverride = (dateKey, config) => {
    setSettings({
      ...settings,
      calendarOverrides: {
        ...overrides,
        [dateKey]: normalizeSearchConfig(config, defaultSearch),
      },
    });
  };

  const clearDateOverride = (dateKey) => {
    const next = { ...overrides };
    delete next[dateKey];
    setSettings({ ...settings, calendarOverrides: next });
  };

  const keepWeekendsOff = () => setSettings({ ...settings, weekendsOff: true });
  const allowWeekends = () => setSettings({ ...settings, weekendsOff: false });
  const cells = calendarCells(calendarMonth);
  const todayKey = localDateKey(new Date());
  const previewCells = cells.slice(0, 14);
  const nextActiveDay = cells.find((date) => configForDate(localDateKey(date)).enabled);

  return (
    <motion.main className="page" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
      <section className="page-heading">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Search settings.</h1>
        </div>
        <button className="dark" onClick={saveAll} disabled={saving}>
          {saving ? <Loader2 className="spin" size={18} /> : <Check size={18} />}
          Save
        </button>
      </section>
      {message && <p className="notice-line">{message}</p>}

      <section className="settings-section">
        <div className="section-title">
          <CalendarDays size={20} />
          <div>
            <strong>Search calendar</strong>
            <span>Compact previews stay visible here. Open either surface when you need the full editor.</span>
          </div>
        </div>
        <div className="settings-feature-grid">
          <article className="settings-preview-card calendar-preview-card">
            <div className="settings-preview-head">
              <div>
                <span>Calendar</span>
                <strong>{monthLabel(calendarMonth)}</strong>
              </div>
              <button onClick={() => setCalendarOpen(true)}>Open</button>
            </div>
            <div className="calendar-mini-weekdays">
              {DAY_NAMES.map((day) => <span key={day}>{day.slice(0, 1)}</span>)}
            </div>
            <div className="calendar-mini-grid">
              {previewCells.map((date) => {
                const key = localDateKey(date);
                const isCurrentMonth = date.getMonth() === calendarMonth.getMonth();
                const hasOverride = Boolean(overrides[key]);
                const config = configForDate(key);
                return (
                  <button
                    key={key}
                    className={cls("calendar-mini-day", !isCurrentMonth && "is-muted", key === todayKey && "is-today", hasOverride && "has-override", !config.enabled && "is-off")}
                    onClick={() => {
                      setCalendarOpen(true);
                      setSelectedDate(key);
                    }}
                  >
                    {date.getDate()}
                  </button>
                );
              })}
            </div>
            <div className="settings-preview-meta">
              <span>{Object.keys(overrides).length} overrides</span>
              <span>{settings.weekendsOff ? "Weekends off" : "Weekends live"}</span>
              <span>{nextActiveDay ? `Next live day ${nextActiveDay.getDate()}` : "No active days"}</span>
            </div>
          </article>

          <article className="settings-preview-card default-search-preview">
            <div className="settings-preview-head">
              <div>
                <span>Default search</span>
                <strong>{defaultSearch.businessType} in {defaultSearch.location}</strong>
              </div>
              <button onClick={() => setDefaultEditorOpen(true)}>Open</button>
            </div>
            <div className="default-stats">
              <span>{defaultSearch.numLeads} leads</span>
              <span>{defaultSearch.minRating}+ stars</span>
              <span>{defaultSearch.maxUserReviews} max reviews</span>
            </div>
            <div className="settings-preview-body">
              <p>{defaultSearch.searchMode === "qualified_no_website" ? "Only businesses without owned websites" : "All businesses in the selected market"}</p>
              <div className="settings-preview-chips">
                <strong className={defaultSearch.enabled ? "ready" : ""}>{defaultSearch.enabled ? "Search on" : "Search off"}</strong>
                <strong>{settings.weekendsOff ? "Weekends off" : "Weekends on"}</strong>
              </div>
            </div>
          </article>
        </div>
      </section>

      <AnimatePresence>
        {calendarOpen && (
          <motion.div className="calendar-popover-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.aside className="calendar-popover calendar-browser-popover" initial={{ opacity: 0, y: 18, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 18, scale: 0.98 }}>
              <header>
                <div>
                  <span>Search calendar</span>
                  <h2>{monthLabel(calendarMonth)}</h2>
                </div>
                <button onClick={() => setCalendarOpen(false)} aria-label="Close calendar browser">
                  <X size={20} />
                </button>
              </header>
              <div className="calendar-browser-toolbar">
                <button onClick={() => setCalendarMonth(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() - 1, 1))}>Prev</button>
                <button onClick={() => setCalendarMonth(new Date())}>Today</button>
                <button onClick={() => setCalendarMonth(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1, 1))}>Next</button>
              </div>
              <div className="calendar-weekdays">
                {DAY_NAMES.map((day) => <span key={day}>{day}</span>)}
              </div>
              <div className="calendar-grid">
                {cells.map((date) => {
                  const key = localDateKey(date);
                  const isCurrentMonth = date.getMonth() === calendarMonth.getMonth();
                  const hasOverride = Boolean(overrides[key]);
                  const config = configForDate(key);
                  return (
                    <button
                      key={key}
                      className={cls("calendar-day", !isCurrentMonth && "is-muted", key === todayKey && "is-today", hasOverride && "has-override", !config.enabled && "is-off")}
                      onClick={() => setSelectedDate(key)}
                    >
                      <strong>{date.getDate()}</strong>
                      <span>{config.enabled ? `${config.businessType} ? ${config.numLeads}` : "Off"}</span>
                    </button>
                  );
                })}
              </div>
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {defaultEditorOpen && (
          <DefaultSearchEditor
            config={defaultSearch}
            weekendsOff={settings.weekendsOff}
            onChange={setDefaultSearch}
            onKeepWeekendsOff={keepWeekendsOff}
            onAllowWeekends={allowWeekends}
            onClose={() => setDefaultEditorOpen(false)}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {selectedDate && (
          <SelectedDayEditor
            dateKey={selectedDate}
            config={configForDate(selectedDate)}
            inherited={!overrides[selectedDate]}
            onChange={(config) => setDateOverride(selectedDate, config)}
            onClear={() => clearDateOverride(selectedDate)}
            onClose={() => setSelectedDate("")}
          />
        )}
      </AnimatePresence>

      <section className="settings-section">
        <div className="section-title">
          <Bell size={20} />
          <div>
            <strong>Email notification</strong>
            <span>Sent after the 5 AM run if SMTP credentials are configured.</span>
          </div>
        </div>
        <div className="settings-grid">
          <label>
            <span>Recipient</span>
            <input value={settings.notificationEmail || ""} onChange={(event) => setSettings({ ...settings, notificationEmail: event.target.value })} />
          </label>
          <button className={settings.emailNotificationsEnabled ? "toggle is-on" : "toggle"} onClick={() => setSettings({ ...settings, emailNotificationsEnabled: !settings.emailNotificationsEnabled })}>
            {settings.emailNotificationsEnabled ? "Notifications on" : "Notifications off"}
          </button>
          <button className={settings.dailyAutomationEnabled ? "toggle is-on" : "toggle"} onClick={() => setSettings({ ...settings, dailyAutomationEnabled: !settings.dailyAutomationEnabled })}>
            {settings.dailyAutomationEnabled ? "Daily automation on" : "Daily automation off"}
          </button>
        </div>
      </section>

      <section className="settings-section">
        <div className="section-title">
          <Eye size={20} />
          <div>
            <strong>Lead display columns</strong>
            <span>Choose what appears on Today and All Leads rows.</span>
          </div>
        </div>
        <div className="column-picker">
          {COLUMN_OPTIONS.map(([key, label]) => (
            <button key={key} className={(settings.visibleColumns || DEFAULT_COLUMNS).includes(key) ? "is-selected" : ""} onClick={() => toggleColumn(key)}>
              {label}
            </button>
          ))}
        </div>
      </section>
    </motion.main>
  );
}
function App() {
  const [page, setPage] = useState("today");
  const [bootstrap, setBootstrap] = useState(null);
  const [settings, setSettings] = useState({ visibleColumns: DEFAULT_COLUMNS });

  useEffect(() => {
    api("/api/app/bootstrap")
      .then((data) => {
        setBootstrap(data);
        setSettings({
          ...data.settings,
          visibleColumns: data.settings?.visibleColumns || DEFAULT_COLUMNS,
          defaultSearch: normalizeSearchConfig(data.settings?.defaultSearch || DEFAULT_SEARCH),
          calendarOverrides: data.settings?.calendarOverrides || {},
        });
      })
      .catch((error) => {
        setBootstrap({ hostedDb: { configured: false }, setupError: error.message, today: new Date().toISOString().slice(0, 10) });
        setSettings({
          visibleColumns: DEFAULT_COLUMNS,
          notificationEmail: "ibrahim.m7004@gmail.com",
          emailNotificationsEnabled: true,
          dailyAutomationEnabled: true,
          weekendsOff: false,
          defaultSearch: DEFAULT_SEARCH,
          calendarOverrides: {},
        });
      });
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div><Sparkles size={20} /></div>
          <span>LeadFlow</span>
        </div>
        <nav className="desktop-nav">
          <button className={page === "today" ? "is-selected" : ""} onClick={() => setPage("today")}>Today</button>
          <button className={page === "all" ? "is-selected" : ""} onClick={() => setPage("all")}>All Leads</button>
          <button className={page === "settings" ? "is-selected" : ""} onClick={() => setPage("settings")}>Settings</button>
        </nav>
      </header>

      <AnimatePresence mode="wait">
        {page === "today" && <TodayPage key="today" bootstrap={bootstrap} settings={settings} setSettings={setSettings} />}
        {page === "all" && <AllLeadsPage key="all" settings={settings} />}
        {page === "settings" && <SettingsPage key="settings" settings={settings} setSettings={setSettings} />}
      </AnimatePresence>

      <nav className="mobile-nav">
        <button className={page === "today" ? "is-selected" : ""} onClick={() => setPage("today")}>
          <Flame size={19} />
          Today
        </button>
        <button className={page === "all" ? "is-selected" : ""} onClick={() => setPage("all")}>
          <Search size={19} />
          All
        </button>
        <button className={page === "settings" ? "is-selected" : ""} onClick={() => setPage("settings")}>
          <Settings size={19} />
          Settings
        </button>
      </nav>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
