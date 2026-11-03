// The slice of the D1 API src/usage_log_worker.js uses, over an in-memory node:sqlite
// database; shared by the worker probes.

import { DatabaseSync } from 'node:sqlite';

export function fakeD1(sql = new DatabaseSync(':memory:')) {
  const statement = (text, args = []) => ({
    bind: (...bound) => statement(text, bound),
    run: async () => { sql.prepare(text).run(...args); return { success: true }; },
    first: async (column) => {
      const row = sql.prepare(text).get(...args);
      if (row === undefined) return null;
      return column ? row[column] : { ...row };
    },
    all: async () => ({ results: sql.prepare(text).all(...args).map((r) => ({ ...r })) }),
    apply: () => sql.prepare(text).run(...args),
  });
  return {
    sql,
    prepare: (text) => statement(text),
    batch: async (statements) => {
      sql.exec('BEGIN');
      try {
        const out = statements.map((s) => s.apply());
        sql.exec('COMMIT');
        return out;
      } catch (err) {
        sql.exec('ROLLBACK');
        throw err;
      }
    },
  };
}
