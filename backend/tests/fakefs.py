"""Minimal in-memory Firestore stand-in for firestore_client."""
import copy

_MISSING = object()

class Snap:
    def __init__(self, id, data):
        self.id = id; self._d = data
    @property
    def exists(self): return self._d is not None
    def to_dict(self): return copy.deepcopy(self._d) if self._d is not None else None

class Doc:
    def __init__(self, store, path):
        self.store = store; self.path = path; self.id = path[-1]
    def collection(self, name): return Coll(self.store, self.path + (name,))
    def get(self, field_paths=None): return Snap(self.id, self.store.docs.get(self.path))
    def set(self, data, merge=False):
        self.store.writes.append((self.path, copy.deepcopy(data), merge))
        if merge and self.path in self.store.docs:
            self.store.docs[self.path].update(copy.deepcopy(data))
        else:
            self.store.docs[self.path] = copy.deepcopy(data)

class Query:
    def __init__(self, coll, filters=(), order=None, lim=None, fields=None):
        self.coll = coll; self.filters = list(filters); self.order = order; self.lim = lim; self.fields = fields
    def _q(self, **kw):
        d = dict(filters=self.filters, order=self.order, lim=self.lim, fields=self.fields); d.update(kw)
        return Query(self.coll, **d)
    def where(self, filter):
        return self._q(filters=self.filters + [filter])
    def order_by(self, field, direction="ASCENDING"):
        return self._q(order=(field, direction))
    def limit(self, n): return self._q(lim=n)
    def select(self, fields): return self._q(fields=list(fields))
    def stream(self):
        self.coll.store.reads.append(("query", self.coll.path, [(f.field_path, str(f.op_string), f.value) for f in self.filters]))
        out = []
        for path, data in self.coll.store.docs.items():
            if path[:-1] != self.coll.path: continue
            ok = True
            for f in self.filters:
                v = data.get(f.field_path, _MISSING)
                if f.value is None:
                    ok = ok and (v is None)          # IS_NULL: explicit null only, not missing
                else:
                    ok = ok and v is not _MISSING and v == f.value
            if ok: out.append((path, data))
        if self.order:
            field, direction = self.order
            present = [(p, d) for p, d in out if d.get(field) is not None]  # firestore drops docs missing the field
            out = sorted(present, key=lambda pd: pd[1][field], reverse=(direction == "DESCENDING"))
        if self.lim is not None: out = out[: self.lim]
        res = []
        for p, d in out:
            dd = {k: d[k] for k in self.fields if k in d} if self.fields else d
            res.append(Snap(p[-1], dd))
        return iter(res)

class Coll(Query):
    def __init__(self, store, path):
        self.store = store; self.path = path
        super().__init__(self)
    def document(self, id): return Doc(self.store, self.path + (id,))

class Batch:
    def __init__(self, store): self.store = store; self.ops = []; self.committed = False
    def set(self, ref, data, merge=False): self.ops.append((ref, data, merge))
    def commit(self):
        self.committed = True
        for ref, data, merge in self.ops: ref.set(data, merge=merge)

class FakeDB:
    def __init__(self):
        self.docs = {}; self.writes = []; self.reads = []; self.batches = []
    def collection(self, name): return Coll(self, (name,))
    def batch(self):
        b = Batch(self); self.batches.append(b); return b
    def get_all(self, refs, field_paths=None):
        self.reads.append(("get_all", len(refs), field_paths))
        for r in refs:
            d = self.docs.get(r.path)
            yield Snap(r.id, ({k: d[k] for k in (field_paths or d) if k in d} if d is not None else None))
    def put_email(self, uid, doc):
        self.docs[("users", uid, "emails", doc["id"])] = copy.deepcopy(doc)
