"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createPerson,
  deletePerson,
  listPeople,
  updatePerson,
  type Person,
} from "@/lib/api";

export default function PeoplePage() {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newAliases, setNewAliases] = useState("");

  const refresh = useCallback(async () => {
    try {
      setPeople(await listPeople());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load people");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      await createPerson({
        name: newName.trim(),
        aliases: parseAliases(newAliases),
        is_me: false,
      });
      setNewName("");
      setNewAliases("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add person");
    }
  }

  async function setMe(p: Person) {
    await updatePerson(p.id, { name: p.name, aliases: p.aliases, is_me: true });
    refresh();
  }

  async function editAliases(p: Person) {
    const input = prompt(`Aliases for ${p.name} (comma-separated):`, p.aliases.join(", "));
    if (input === null) return;
    await updatePerson(p.id, { name: p.name, aliases: parseAliases(input), is_me: p.is_me });
    refresh();
  }

  async function remove(p: Person) {
    if (!confirm(`Remove ${p.name} from the registry?`)) return;
    try {
      await deletePerson(p.id);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>People</h1>
        <span className="muted">Used for speaker mapping and task classification</span>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <form className="upload-card" onSubmit={add}>
        <input
          type="text"
          placeholder="Name (e.g. Rahul)"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <input
          type="text"
          placeholder="Aliases, comma-separated (optional)"
          value={newAliases}
          onChange={(e) => setNewAliases(e.target.value)}
        />
        <button type="submit" disabled={!newName.trim()}>
          Add person
        </button>
      </form>

      {people === null && !error && <div className="empty">Loading…</div>}
      {people && (
        <div className="task-table-wrap">
          <table className="task-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Aliases</th>
                <th>Me?</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {people.map((p) => (
                <tr key={p.id}>
                  <td>
                    <strong>{p.name}</strong>
                  </td>
                  <td>
                    <span className="editable" onClick={() => editAliases(p)}>
                      {p.aliases.length ? p.aliases.join(", ") : "— add aliases"}
                    </span>
                  </td>
                  <td>
                    <input
                      type="radio"
                      name="is_me"
                      checked={p.is_me}
                      onChange={() => setMe(p)}
                      title="Tasks are filtered for this person"
                    />
                  </td>
                  <td>
                    {!p.is_me && (
                      <button className="ghost-danger" onClick={() => remove(p)}>
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function parseAliases(s: string): string[] {
  return s
    .split(",")
    .map((a) => a.trim())
    .filter(Boolean);
}
