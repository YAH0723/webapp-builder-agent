import type Database from "better-sqlite3";
import { randomUUID } from "node:crypto";

export type RecordData = Record<string, unknown>;
export interface Stored<T extends RecordData = RecordData> {
  id: string; data: T; createdAt: string; updatedAt: string;
}
interface Row { id: string; data: string; created_at: string; updated_at: string }
const unpack = <T extends RecordData>(row: Row): Stored<T> => ({
  id: row.id, data: JSON.parse(row.data) as T, createdAt: row.created_at, updatedAt: row.updated_at,
});

// No routes or business defaults are installed. The application decides validation,
// authorization, relationships, response shapes, and whether this store suits its data.
export class DocumentStore {
  constructor(readonly db: Database.Database) {
    db.exec(`CREATE TABLE IF NOT EXISTS arc_records (
      resource TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)),
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(resource,id));`);
  }
  private resource(value: string) {
    if (!/^[A-Za-z][A-Za-z0-9_-]{0,79}$/.test(value)) throw new Error("Invalid resource name");
    return value;
  }
  private encode(value: RecordData): string {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Record must be an object");
    return JSON.stringify(value);
  }
  create<T extends RecordData>(resource: string, data: T, id: string = randomUUID()): Stored<T> {
    const encoded = this.encode(data), now = new Date().toISOString();
    if (!id.trim()) throw new Error("Record id is required");
    this.db.prepare("INSERT INTO arc_records(resource,id,data,created_at,updated_at) VALUES(?,?,?,?,?)")
      .run(this.resource(resource), id, encoded, now, now);
    return {id, data: JSON.parse(encoded) as T, createdAt: now, updatedAt: now};
  }
  get<T extends RecordData = RecordData>(resource: string, id: string): Stored<T> | undefined {
    const row = this.db.prepare("SELECT * FROM arc_records WHERE resource=? AND id=?")
      .get(this.resource(resource), id) as Row | undefined;
    return row && unpack<T>(row);
  }
  list<T extends RecordData = RecordData>(resource: string): Stored<T>[] {
    return (this.db.prepare("SELECT * FROM arc_records WHERE resource=? ORDER BY rowid")
      .all(this.resource(resource)) as Row[]).map(unpack<T>);
  }
  update<T extends RecordData>(resource: string, id: string, changes: Partial<T>): Stored<T> | undefined {
    return this.transaction(() => {
      const old = this.get<T>(resource, id);
      if (!old) return undefined;
      const data = this.encode({...old.data, ...changes});
      this.db.prepare("UPDATE arc_records SET data=?,updated_at=? WHERE resource=? AND id=?")
        .run(data, new Date().toISOString(), resource, id);
      return this.get<T>(resource, id);
    });
  }
  delete(resource: string, id: string): boolean {
    return this.db.prepare("DELETE FROM arc_records WHERE resource=? AND id=?")
      .run(this.resource(resource), id).changes > 0;
  }
  transaction<T>(work: () => T): T { return this.db.transaction(work)(); }
}
