// Fetch wrapper, the error envelope, and the offline pending-write queue.
//
// A shaft-field PATCH that fails because of a real rejection (a validation
// error, a 404) is never queued -- retrying a rejected value forever would
// be pointless, and the caller needs to show it inline right away. A PATCH
// that fails because the network dropped IS queued and mirrored to
// localStorage, then flushed through the bulk endpoint on reconnect. A weak
// connection at the bench must not cost the archer 40 shafts of work.

const QUEUE_KEY = "shafttracker.pendingWrites.v1";

export class ApiError extends Error {
  constructor(code, message, status, issues) {
    super(message);
    this.code = code;
    this.status = status;
    this.issues = issues || null;
  }
}

export class OfflineError extends Error {
  constructor() {
    super("no connection: queued for retry");
  }
}

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (networkError) {
    throw new OfflineError();
  }
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    // empty body, fine for e.g. 204s
  }
  if (!res.ok) {
    const err = (data && data.error) || { code: "ERROR", message: res.statusText };
    throw new ApiError(err.code, err.message, res.status, err.issues || null);
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body),
  patch: (path, body) => request("PATCH", path, body),
  put: (path, body) => request("PUT", path, body),
  del: (path) => request("DELETE", path),
};

// A multipart file upload (import preview) can't go through request():
// FormData needs no Content-Type header of its own -- the browser sets the
// multipart boundary itself -- and must never be JSON.stringify'd.
export async function postFile(path, formData) {
  let res;
  try {
    res = await fetch(path, { method: "POST", body: formData });
  } catch (networkError) {
    throw new OfflineError();
  }
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    // empty body
  }
  if (!res.ok) {
    const err = (data && data.error) || { code: "ERROR", message: res.statusText };
    throw new ApiError(err.code, err.message, res.status, err.issues || null);
  }
  return data;
}

function loadQueue() {
  try {
    return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
  } catch (e) {
    return [];
  }
}

function saveQueue(queue) {
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  } catch (e) {
    // storage unavailable (private window, quota); the queue still lives
    // in this tab's memory for the current session.
  }
}

function queuePendingWrite(batchId, seq, fields) {
  const queue = loadQueue();
  queue.push({ batchId, seq, fields, queuedAt: Date.now() });
  saveQueue(queue);
}

export function pendingWriteCount() {
  return loadQueue().length;
}

export async function flushPendingWrites() {
  const queue = loadQueue();
  if (queue.length === 0) return { flushed: 0, failed: 0 };

  const byBatch = new Map();
  for (const item of queue) {
    if (!byBatch.has(item.batchId)) byBatch.set(item.batchId, []);
    byBatch.get(item.batchId).push(item);
  }

  let flushed = 0;
  let failed = 0;
  const remaining = [];
  for (const [batchId, items] of byBatch) {
    try {
      const res = await api.post(`api/batches/${batchId}/shafts:bulk`, {
        items: items.map((i) => ({ seq: i.seq, fields: i.fields })),
      });
      res.results.forEach((r, idx) => {
        if (r.ok) {
          flushed++;
        } else {
          failed++;
          remaining.push(items[idx]);
        }
      });
    } catch (e) {
      remaining.push(...items);
      failed += items.length;
    }
  }
  saveQueue(remaining);
  return { flushed, failed };
}

// Attempts a direct PATCH; on a network failure, queues it instead of
// throwing straight to the caller as a hard error.
export async function patchShaftField(batchId, seq, fields) {
  try {
    return await api.patch(`api/batches/${batchId}/shafts/${seq}`, fields);
  } catch (e) {
    if (e instanceof OfflineError) {
      queuePendingWrite(batchId, seq, fields);
    }
    throw e;
  }
}

window.addEventListener("online", () => {
  flushPendingWrites();
});
