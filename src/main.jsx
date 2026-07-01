import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

const RAW_API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const API_BASE = RAW_API_BASE.replace(/\/$/, "");
const API_BASE_IS_LOCALHOST = /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/i.test(API_BASE);
const FRONTEND_IS_LOCALHOST = typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname);

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

const INITIAL_SETTINGS = {
  visibleColumns: DEFAULT_COLUMNS,
  notificationEmail: "ibrahim.m7004@gmail.com",
  emailNotificationsEnabled: true,
  dailyAutomationEnabled: true,
  weekendsOff: false,
  defaultSearch: DEFAULT_SEARCH,
  calendarOverrides: {},
};

function normalizeSearchConfig(value = {}, fallback = DEFAULT_SEARCH) {
  return {
    ...fallback,
    ...Object.fromEntries(Object.entries(value || {}).filter(([, item]) => item !== undefined && item !== null)),
  };
}

function normalizeAppSettings(value = {}) {
  return {
    ...INITIAL_SETTINGS,
    ...value,
    visibleColumns: value?.visibleColumns?.length ? value.visibleColumns : DEFAULT_COLUMNS,
    defaultSearch: normalizeSearchConfig(value?.defaultSearch || DEFAULT_SEARCH),
    calendarOverrides: value?.calendarOverrides || {},
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

function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stableValue(value[key])]));
  }
  return value;
}

function serializeSettings(value) {
  return JSON.stringify(stableValue(value || {}));
}

async function api(path, options = {}, retryOptions = {}) {
  const { attempts = 1, delayMs = 0, retryStatuses = [502, 503, 504], onRetry } = retryOptions;
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(data.detail || `Request failed (${response.status}).`);
        error.status = response.status;
        throw error;
      }
      return data;
    } catch (error) {
      const originalError = error instanceof Error ? error : new Error("Request failed.");
      const retryableNetwork = originalError.message === "Failed to fetch";
      lastError = originalError;
      if (retryableNetwork) {
        const localHint = API_BASE_IS_LOCALHOST && !FRONTEND_IS_LOCALHOST
          ? " The deployed frontend is trying to call localhost; set VITE_API_BASE_URL in Vercel to the Render backend URL and redeploy the frontend."
          : " Check CORS/ALLOWED_ORIGINS on the backend and confirm the API URL is reachable from the browser.";
        lastError = new Error(`Failed to reach backend at ${API_BASE}.${localHint}`);
      }
      const retryableStatus = retryStatuses.includes(lastError.status);
      if (attempt >= attempts || (!retryableNetwork && !retryableStatus)) break;
      if (onRetry) onRetry({ attempt, error: lastError });
      if (delayMs) await wait(delayMs);
    }
  }
  throw lastError || new Error("Request failed.");
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

function getAudit(row) {
  return row?.auditResult && typeof row.auditResult === "object" ? row.auditResult : {};
}

function scoreNumber(value) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? Math.max(0, Math.min(100, parsed)) : 0;
}

function leadQualityLabel(score) {
  if (score >= 75) return "Good lead";
  if (score >= 50) return "Promising lead";
  if (score >= 30) return "Weak lead";
  return "Bad lead";
}

function satisfactionColor(score) {
  if (score >= 75) return "#15965f";
  if (score >= 50) return "#d49a1f";
  if (score >= 30) return "#e56b2f";
  return "#c9342f";
}

function formatAction(value) {
  return String(value || "manual_research_needed").replaceAll("_", " ");
}

function listValue(value) {
  return Array.isArray(value) ? value : [];
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
  if (!bootstrap) return null;
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

function BackendWakeNotice({ backendState, onRetry }) {
  if (backendState.status === "ready") return null;
  const waking = backendState.status === "waking";
  return (
    <section className={cls("setup-strip", "wake-strip", waking && "is-waking", backendState.status === "error" && "is-error")}>
      {waking ? <Loader2 className="spin" size={20} /> : <Clock3 size={20} />}
      <div>
        <strong>{waking ? "Waking backend" : "Backend unavailable"}</strong>
        <p>
          {waking
            ? "Render is waking up. The app will load live settings and leads as soon as the backend responds."
            : "The backend did not respond yet. Retry to wake it again and keep the tab open for a minute."}
        </p>
        {backendState.message && <small>{backendState.message}</small>}
      </div>
      {!waking && (
        <button onClick={onRetry}>
          <RefreshCw size={16} />
          Retry
        </button>
      )}
    </section>
  );
}

function SyncBadge({ syncState }) {
  const labelByStatus = {
    synced: "Synced",
    saving: "Saving",
    dirty: "Pending save",
    waking: "Retrying backend",
    error: "Save failed",
  };
  if (!syncState?.status) return null;
  return <span className={cls("sync-badge", `is-${syncState.status}`)}>{labelByStatus[syncState.status] || syncState.status}</span>;
}

function LeadRow({ row, visibleColumns, onTick, onDebug, onAudit, auditing }) {
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
          {row.auditStatus && <strong className="ready">Audited</strong>}
        </div>
        <div className="lead-actions">
          {row.googleMapsUri && (
            <a className="action-button" href={row.googleMapsUri} target="_blank" rel="noreferrer">
              <ExternalLink size={16} />
              Map
            </a>
          )}
          {onAudit && (
            <button className="action-button audit-action" onClick={() => onAudit(row)} disabled={auditing}>
              {auditing ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}
              {auditing ? "Auditing" : row.auditStatus ? "Re-audit" : "Audit"}
            </button>
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
  const audit = getAudit(row);
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
          <h3>Website audit</h3>
          <dl>
            <dt>Status</dt>
            <dd>{row.auditStatus || "Not audited"}</dd>
            <dt>Website status</dt>
            <dd>{row.auditWebsiteStatus || audit.website_status || "None"}</dd>
            <dt>Lead quality</dt>
            <dd>{row.auditLeadQualityScore || audit.lead_quality_score || 0}</dd>
            <dt>Priority</dt>
            <dd>{row.auditOutreachPriority || audit.outreach_priority || "None"}</dd>
            <dt>Next action</dt>
            <dd>{formatAction(row.auditNextBestAction || audit.next_best_action)}</dd>
            <dt>Pitch</dt>
            <dd>{row.auditRecommendedPitchAngle || audit.recommended_pitch_angle || "None"}</dd>
          </dl>
        </section>
        <section>
          <h3>Audit Debug</h3>
          <pre>{JSON.stringify(audit, null, 2) || "{}"}</pre>
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

function TodayPage({ bootstrap, settings, setSettings, backendState, onWakeBackend }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("ai_decision");
  const [enriching, setEnriching] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0, found: 0, ai: 0, pages: 0 });
  const [debugRow, setDebugRow] = useState(null);
  const [auditingIds, setAuditingIds] = useState(() => new Set());
  const [runSummary, setRunSummary] = useState(bootstrap?.latestRun || {});
  const visibleColumns = settings.visibleColumns?.length ? settings.visibleColumns : DEFAULT_COLUMNS;

  const loadToday = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api("/api/app/leads/today", {}, {
        attempts: 3,
        delayMs: 2500,
        onRetry: () => setError("Waking backend and retrying today's leads..."),
      });
      setRows(data.rows || []);
      setRunSummary(data.runSummary || {});
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (backendState.status !== "ready") {
      setLoading(false);
      return;
    }
    if (bootstrap?.hostedDb?.configured) loadToday();
    else setLoading(false);
  }, [backendState.status, bootstrap?.hostedDb?.configured]);

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

  const auditLead = async (row) => {
    setAuditingIds((current) => new Set([...current, row.id]));
    setError("");
    try {
      const data = await api(`/api/app/leads/${row.id}/audit`, {
        method: "POST",
        body: JSON.stringify({ enableVisualAudit: true, storeResults: true }),
      });
      updateRow(data.row);
    } catch (err) {
      setError(err.message);
    } finally {
      setAuditingIds((current) => {
        const next = new Set(current);
        next.delete(row.id);
        return next;
      });
    }
  };

  const runDailyNow = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api("/api/app/run-daily", { method: "POST", body: JSON.stringify({ notify: false }) }, {
        attempts: 3,
        delayMs: 2500,
        onRetry: () => setError("Waking backend and retrying the daily run..."),
      });
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
      <BackendWakeNotice backendState={backendState} onRetry={onWakeBackend} />
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
            <LeadRow
              key={row.id}
              row={row}
              visibleColumns={visibleColumns}
              onTick={tickLead}
              onDebug={setDebugRow}
              onAudit={auditLead}
              auditing={auditingIds.has(row.id)}
            />
          ))}
        </AnimatePresence>
        {!loading && backendState.status === "ready" && !sortedRows.length && (
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

function AllLeadsPage({ settings, backendState, onWakeBackend }) {
  const [rows, setRows] = useState([]);
  const [filters, setFilters] = useState({ q: "", dateFrom: "", dateTo: "", ticked: "", hasEmail: "", minRating: "", maxReviews: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [debugRow, setDebugRow] = useState(null);
  const [auditingIds, setAuditingIds] = useState(() => new Set());
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
      const data = await api(`/api/app/leads?${params.toString()}`, {}, {
        attempts: 3,
        delayMs: 2500,
        onRetry: () => setError("Waking backend and retrying the archive..."),
      });
      setRows(data.rows || []);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (backendState.status === "ready") load();
  }, [backendState.status]);

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

  const auditLead = async (row) => {
    setAuditingIds((current) => new Set([...current, row.id]));
    setError("");
    try {
      const data = await api(`/api/app/leads/${row.id}/audit`, {
        method: "POST",
        body: JSON.stringify({ enableVisualAudit: true, storeResults: true }),
      });
      setRows((current) => current.map((item) => (item.id === row.id ? data.row : item)));
    } catch (err) {
      setError(err.message);
    } finally {
      setAuditingIds((current) => {
        const next = new Set(current);
        next.delete(row.id);
        return next;
      });
    }
  };

  return (
    <motion.main className="page" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
      <BackendWakeNotice backendState={backendState} onRetry={onWakeBackend} />
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
          <LeadRow
            key={row.id}
            row={row}
            visibleColumns={visibleColumns}
            onTick={tickLead}
            onDebug={setDebugRow}
            onAudit={auditLead}
            auditing={auditingIds.has(row.id)}
          />
        ))}
      </section>
      <AnimatePresence>
        {debugRow && <DebugPanel row={debugRow} onClose={() => setDebugRow(null)} />}
      </AnimatePresence>
    </motion.main>
  );
}

function SatisfactionBar({ score }) {
  const safeScore = scoreNumber(score);
  return (
    <div className="satisfaction-wrap">
      <div className="satisfaction-meta">
        <strong>{leadQualityLabel(safeScore)}</strong>
        <span>{safeScore}/100</span>
      </div>
      <div className="satisfaction-bar" aria-label={`Lead quality ${safeScore} out of 100`}>
        <div style={{ width: `${safeScore}%`, background: satisfactionColor(safeScore) }} />
      </div>
    </div>
  );
}

function OutreachCard({ row, onAudit, auditing, onDebug }) {
  const audit = getAudit(row);
  const score = scoreNumber(row.auditLeadQualityScore || audit.lead_quality_score);
  const opportunity = scoreNumber(row.auditWebsiteOpportunityScore || audit.website_opportunity_score);
  const impactIssues = listValue(audit.top_business_impact_issues);
  const verifiedIssues = listValue(audit.top_verified_issues);
  const issues = impactIssues.length ? impactIssues : verifiedIssues;
  const channels = listValue(audit.contact_channels);
  const pitch = row.auditRecommendedPitchAngle || audit.recommended_pitch_angle || "No pitch angle captured.";
  const website = row.websiteUrl || row.externalWebsiteUrl || audit.final_url || "";

  return (
    <motion.article className="outreach-card" layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <div className="outreach-identity">
        <div className="lead-kicker">
          <span>{row.auditOutreachPriority || audit.outreach_priority || "priority"}</span>
          <span>{formatDate(row.auditedAt)}</span>
        </div>
        <h3>{row.name || audit.business_name || "Unnamed business"}</h3>
        <p>{row.businessType || audit.business_category || row.searchQuery || "Local business"}</p>
        <div className="outreach-links">
          {website && <a href={website} target="_blank" rel="noreferrer">Website</a>}
          {row.googleMapsUri && <a href={row.googleMapsUri} target="_blank" rel="noreferrer">Map</a>}
          {row.phone && <a href={`tel:${row.phone}`}>Call</a>}
        </div>
      </div>

      <div className="outreach-visual-column">
        <SatisfactionBar score={score} />
        <div className="outreach-score-grid">
          <span>Opportunity <strong>{opportunity}</strong></span>
          <span>Visual <strong>{audit.visual_score ?? 0}</strong></span>
          <span>Conversion <strong>{audit.conversion_issue_score ?? 0}</strong></span>
        </div>
      </div>

      <div className="outreach-insights">
        <strong>{row.auditRecommendedPitchType || audit.recommended_pitch_type || "Pitch angle"}</strong>
        <p>{pitch}</p>
        <ul>
          {issues.slice(0, 4).map((issue) => <li key={issue}>{issue}</li>)}
          {!issues.length && <li>No major audit issues captured.</li>}
        </ul>
      </div>

      <div className="outreach-next">
        <span>Next best action</span>
        <strong>{formatAction(row.auditNextBestAction || audit.next_best_action)}</strong>
        <small>{channels.length ? `Channels: ${channels.join(", ")}` : row.bestEmail ? "Email available" : "No contact channel captured"}</small>
        <button className="dark" onClick={() => onAudit(row)} disabled={auditing}>
          {auditing ? <Loader2 className="spin" size={17} /> : <Sparkles size={17} />}
          {auditing ? "Auditing" : "Re-audit"}
        </button>
        <button onClick={() => onDebug(row)}>
          <Eye size={17} />
          Details
        </button>
      </div>
    </motion.article>
  );
}

function OutreachPage({ backendState, onWakeBackend }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [auditingIds, setAuditingIds] = useState(() => new Set());
  const [debugRow, setDebugRow] = useState(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api("/api/app/outreach", {}, {
        attempts: 3,
        delayMs: 2500,
        onRetry: () => setError("Waking backend and retrying outreach leads..."),
      });
      setRows(data.rows || []);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (backendState.status === "ready") load();
  }, [backendState.status]);

  const auditLead = async (row) => {
    setAuditingIds((current) => new Set([...current, row.id]));
    setError("");
    try {
      const data = await api(`/api/app/leads/${row.id}/audit`, {
        method: "POST",
        body: JSON.stringify({ enableVisualAudit: true, storeResults: true }),
      });
      setRows((current) => current.map((item) => (item.id === row.id ? data.row : item)));
    } catch (err) {
      setError(err.message);
    } finally {
      setAuditingIds((current) => {
        const next = new Set(current);
        next.delete(row.id);
        return next;
      });
    }
  };

  const sortedRows = useMemo(
    () => [...rows].sort((a, b) => scoreNumber(b.auditLeadQualityScore || getAudit(b).lead_quality_score) - scoreNumber(a.auditLeadQualityScore || getAudit(a).lead_quality_score)),
    [rows],
  );
  const goodCount = rows.filter((row) => scoreNumber(row.auditLeadQualityScore || getAudit(row).lead_quality_score) >= 75).length;
  const avgScore = rows.length ? Math.round(rows.reduce((sum, row) => sum + scoreNumber(row.auditLeadQualityScore || getAudit(row).lead_quality_score), 0) / rows.length) : 0;

  return (
    <motion.main className="page" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}>
      <BackendWakeNotice backendState={backendState} onRetry={onWakeBackend} />
      <section className="archive-hero">
        <div>
          <p className="eyebrow">Outreach</p>
          <h1>Audited lead queue.</h1>
          <p className="hero-subcopy">Every audited lead lands here with its opportunity score, next action, pitch angle, and highest-impact website issues.</p>
        </div>
        <button onClick={load} disabled={loading}>
          {loading ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
          Refresh
        </button>
      </section>

      <section className="archive-stats">
        <Metric label="Audited" value={rows.length} />
        <Metric label="Good leads" value={goodCount} tone="hot" />
        <Metric label="Avg quality" value={avgScore} />
        <Metric label="Needs action" value={rows.filter((row) => (row.auditNextBestAction || getAudit(row).next_best_action) !== "skip").length} />
      </section>

      {error && <p className="error-line">{error}</p>}
      <section className="outreach-list">
        {sortedRows.map((row) => (
          <OutreachCard
            key={row.id}
            row={row}
            onAudit={auditLead}
            auditing={auditingIds.has(row.id)}
            onDebug={setDebugRow}
          />
        ))}
        {!loading && backendState.status === "ready" && !sortedRows.length && (
          <div className="empty-state">
            <Sparkles size={28} />
            <strong>No audited leads yet</strong>
            <p>Use the Audit button on Today or All Leads to validate a lead and send it here.</p>
          </div>
        )}
      </section>
      <AnimatePresence>
        {debugRow && <DebugPanel row={debugRow} onClose={() => setDebugRow(null)} />}
      </AnimatePresence>
    </motion.main>
  );
}

function SettingsPage({ settings, setSettings, backendState, onWakeBackend, syncState, onFlushSettings, effectiveSearch, bootstrap }) {
  const [calendarMonth, setCalendarMonth] = useState(new Date());
  const [selectedDate, setSelectedDate] = useState("");
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [defaultEditorOpen, setDefaultEditorOpen] = useState(false);
  const defaultSearch = normalizeSearchConfig(settings.defaultSearch || DEFAULT_SEARCH);
  const overrides = settings.calendarOverrides && typeof settings.calendarOverrides === "object" ? settings.calendarOverrides : {};
  const tomorrowPreview = effectiveSearch?.tomorrow || null;
  const editable = backendState.status === "ready" && bootstrap?.hostedDb?.configured !== false && !bootstrap?.setupError;

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
      <BackendWakeNotice backendState={backendState} onRetry={onWakeBackend} />
      <section className="page-heading">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Search settings.</h1>
        </div>
        <div className="settings-heading-actions">
          <SyncBadge syncState={syncState} />
          <button className="dark" onClick={onFlushSettings} disabled={!editable || syncState.status === "saving"}>
            {syncState.status === "saving" ? <Loader2 className="spin" size={18} /> : <Check size={18} />}
            Sync now
          </button>
        </div>
      </section>

      <section className="settings-status-strip">
        <div>
          <strong>Tomorrow 5:00 AM run</strong>
          <p>
            {tomorrowPreview
              ? tomorrowPreview.enabled
                ? `${tomorrowPreview.query} • ${tomorrowPreview.config.numLeads} leads • ${tomorrowPreview.config.minRating}+ stars • ${tomorrowPreview.config.maxUserReviews} max reviews`
                : `${tomorrowPreview.query} • disabled`
              : "Waiting for backend schedule confirmation."}
          </p>
        </div>
        <div className="settings-status-meta">
          <span>{tomorrowPreview?.source === "override" ? "Date override" : "Default search"}</span>
          <span>{syncState.message || "Changes auto-save after a short pause."}</span>
        </div>
      </section>

      <fieldset className="settings-fieldset" disabled={!editable}>
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
                <button onClick={() => setCalendarOpen(true)} disabled={!editable}>Open</button>
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
                      disabled={!editable}
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
                <button onClick={() => setDefaultEditorOpen(true)} disabled={!editable}>Open</button>
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
                        <span>{config.enabled ? `${config.businessType} • ${config.numLeads}` : "Off"}</span>
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
      </fieldset>
    </motion.main>
  );
}
function App() {
  const [page, setPage] = useState("today");
  const [bootstrap, setBootstrap] = useState(null);
  const [settings, setSettingsState] = useState(INITIAL_SETTINGS);
  const [effectiveSearch, setEffectiveSearch] = useState({});
  const [backendState, setBackendState] = useState({ status: "waking", message: "Connecting to backend..." });
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [syncState, setSyncState] = useState({ status: "", message: "" });
  const lastSavedSettingsRef = useRef(serializeSettings(INITIAL_SETTINGS));
  const saveTimerRef = useRef(null);

  const setSettings = useCallback((nextOrUpdater) => {
    setSettingsState((current) => normalizeAppSettings(typeof nextOrUpdater === "function" ? nextOrUpdater(current) : nextOrUpdater));
  }, []);

  const loadBootstrap = useCallback(async () => {
    setBackendState({ status: "waking", message: "Waking Render backend..." });
    try {
      const data = await api("/api/app/bootstrap", {}, {
        attempts: 20,
        delayMs: 3000,
        onRetry: ({ attempt }) => {
          setBackendState({ status: "waking", message: `Waking backend... attempt ${attempt + 1} of 20.` });
        },
      });
      const normalizedSettings = normalizeAppSettings(data.settings || {});
      setBootstrap(data);
      setEffectiveSearch(data.effectiveSearch || {});
      setSettingsState(normalizedSettings);
      setSettingsLoaded(true);
      lastSavedSettingsRef.current = serializeSettings(normalizedSettings);
      setBackendState({ status: "ready", message: "" });
      setSyncState({ status: "synced", message: "Backend connected. Settings are live." });
    } catch (error) {
      setBackendState({ status: "error", message: error.message });
      setSyncState((current) => (current.status === "saving" ? { status: "error", message: error.message } : current));
    }
  }, []);

  const flushSettings = useCallback(async (snapshot) => {
    if (!settingsLoaded || backendState.status !== "ready") return false;
    const payloadSettings = normalizeAppSettings(snapshot);
    const snapshotSerialized = serializeSettings(payloadSettings);
    setSyncState({ status: "saving", message: "Saving changes to backend..." });
    try {
      const response = await api("/api/app/settings", {
        method: "PUT",
        body: JSON.stringify({ settings: payloadSettings }),
      }, {
        attempts: 3,
        delayMs: 2500,
        onRetry: () => setSyncState({ status: "waking", message: "Waking backend and retrying settings save..." }),
      });
      const confirmedSettings = normalizeAppSettings(response.settings || payloadSettings);
      const confirmedSerialized = serializeSettings(confirmedSettings);
      lastSavedSettingsRef.current = confirmedSerialized;
      if (response.effectiveSearch) setEffectiveSearch(response.effectiveSearch);
      setBootstrap((current) => (current ? { ...current, settings: confirmedSettings, effectiveSearch: response.effectiveSearch || current.effectiveSearch } : current));
      setSettingsState((current) => (serializeSettings(current) === snapshotSerialized ? confirmedSettings : current));
      setSyncState({ status: "synced", message: "All changes saved." });
      return true;
    } catch (error) {
      setSyncState({ status: "error", message: error.message });
      return false;
    }
  }, [backendState.status, settingsLoaded]);

  const flushCurrentSettings = useCallback(async () => {
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    await flushSettings(settings);
  }, [flushSettings, settings]);

  useEffect(() => {
    loadBootstrap();
  }, [loadBootstrap]);

  useEffect(() => {
    if (!settingsLoaded || backendState.status !== "ready") return undefined;
    const serialized = serializeSettings(settings);
    if (serialized === lastSavedSettingsRef.current) return undefined;
    setSyncState((current) => (current.status === "saving" ? current : { status: "dirty", message: "Unsaved changes pending." }));
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(() => {
      flushSettings(settings);
    }, 900);
    return () => {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
    };
  }, [settings, settingsLoaded, backendState.status, flushSettings]);

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
          <button className={page === "outreach" ? "is-selected" : ""} onClick={() => setPage("outreach")}>Outreach</button>
          <button className={page === "settings" ? "is-selected" : ""} onClick={() => setPage("settings")}>Settings</button>
        </nav>
      </header>

      <AnimatePresence mode="wait">
        {page === "today" && <TodayPage key="today" bootstrap={bootstrap} settings={settings} setSettings={setSettings} backendState={backendState} onWakeBackend={loadBootstrap} />}
        {page === "all" && <AllLeadsPage key="all" settings={settings} backendState={backendState} onWakeBackend={loadBootstrap} />}
        {page === "outreach" && <OutreachPage key="outreach" backendState={backendState} onWakeBackend={loadBootstrap} />}
        {page === "settings" && <SettingsPage key="settings" settings={settings} setSettings={setSettings} backendState={backendState} onWakeBackend={loadBootstrap} syncState={syncState} onFlushSettings={flushCurrentSettings} effectiveSearch={effectiveSearch} bootstrap={bootstrap} />}
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
        <button className={page === "outreach" ? "is-selected" : ""} onClick={() => setPage("outreach")}>
          <Sparkles size={19} />
          Outreach
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
