"use client";

import { useCallback, useEffect, useState } from "react";
import type { Account, Hotel } from "@/lib/agent";
import { useI18n } from "./I18n";

const MIN_PASSWORD = 10; // as the agent requires
const MAX_ID = 2_147_483_647;

type Form = {
  name: string;
  email: string;
  phone: string;
  uniqueid: string;
  notes: string;
  password: string;
  is_admin: boolean;
  active: boolean;
  hotel_ids: number[];
};

const EMPTY: Form = {
  name: "", email: "", phone: "", uniqueid: "", notes: "", password: "", is_admin: false, active: true, hotel_ids: [],
};

const input =
  "mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-accent dark:border-stone-700 dark:bg-stone-900";
const button = "rounded-lg border border-stone-200 px-3 py-1.5 text-sm hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-900";
const primary = "rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50";

export default function AdminPanel({ me }: { me: Account }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"users" | "hotels">("users");
  const [users, setUsers] = useState<Account[]>([]);
  const [hotels, setHotels] = useState<Hotel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // null: no form; "new": creating; a user: editing them.
  const [editing, setEditing] = useState<Account | "new" | null>(null);

  /** Calls the admin API; returns the JSON body, or null after showing the error. */
  const api = useCallback(
    async (path: string, method = "GET", body?: unknown) => {
      setError(null);
      try {
        const r = await fetch(`/api/admin/${path}`, {
          method,
          headers: body === undefined ? {} : { "content-type": "application/json" },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        if (r.status === 204) return {};
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
          setError(typeof data.detail === "string" ? data.detail : t.invalidFields);
          return null;
        }
        return data;
      } catch {
        setError(t.serviceUnreachable);
        return null;
      }
    },
    [t],
  );

  const load = useCallback(async () => {
    const [u, h] = await Promise.all([api("users"), api("hotels")]);
    if (u) setUsers(u.users);
    if (h) setHotels(h.hotels);
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  const codes = (ids: number[]) =>
    hotels.filter((h) => ids.includes(h.id)).map((h) => h.code).join(", ") || t.noHotelsAssigned;

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6">
      <header className="flex flex-wrap items-center gap-3">
        <div className="flex size-8 items-center justify-center rounded-lg bg-accent text-sm font-bold text-white">P</div>
        <h1 className="text-lg font-semibold">{t.adminTitle}</h1>
        <a href="/" className="ml-auto text-sm text-accent hover:underline">{t.backToChat}</a>
      </header>

      <nav role="tablist" className="mt-6 flex gap-1 border-b border-stone-200 dark:border-stone-800">
        {(["users", "hotels"] as const).map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => {
              setTab(key);
              setNotice(null);
            }}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === key ? "border-accent font-medium" : "border-transparent text-stone-500 hover:text-stone-800 dark:hover:text-stone-200"}`}
          >
            {key === "users" ? t.usersTab : t.hotelsTab}
          </button>
        ))}
      </nav>

      {error && (
        <p role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}
      {notice && !error && (
        <p role="status" className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
          {notice}
        </p>
      )}

      {tab === "users" ? (
        editing ? (
          <UserForm
            key={editing === "new" ? "new" : editing.id}
            user={editing === "new" ? null : editing}
            me={me}
            hotels={hotels}
            onCancel={() => setEditing(null)}
            onSubmit={async (form) => {
              const body: Partial<Form> = { ...form };
              if (editing !== "new" && !form.password) delete body.password;
              const saved = editing === "new" ? await api("users", "POST", body) : await api(`users/${editing.id}`, "PATCH", body);
              if (saved) {
                setEditing(null);
                setNotice(t.saved);
                await load();
              }
            }}
            onDelete={
              editing !== "new" && editing.id !== me.id
                ? async () => {
                    if (!window.confirm(t.confirmDeleteUser(editing.name))) return;
                    if (await api(`users/${editing.id}`, "DELETE")) {
                      setEditing(null);
                      await load();
                    }
                  }
                : undefined
            }
          />
        ) : (
          <section className="mt-4">
            <button className={primary} onClick={() => { setNotice(null); setEditing("new"); }}>{t.newUser}</button>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-stone-200 text-xs text-stone-500 dark:border-stone-800">
                  <tr>
                    <th className="py-2 pr-3 font-medium">{t.fieldName}</th>
                    <th className="py-2 pr-3 font-medium">{t.fieldEmail}</th>
                    <th className="py-2 pr-3 font-medium">{t.fieldUniqueId}</th>
                    <th className="py-2 pr-3 font-medium">{t.roleLabel}</th>
                    <th className="py-2 pr-3 font-medium">{t.colHotels}</th>
                    <th className="py-2 pr-3 font-medium">{t.statusLabel}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id} className="border-b border-stone-100 dark:border-stone-900">
                      <td className="py-2 pr-3">{u.name}</td>
                      <td className="py-2 pr-3">{u.email}</td>
                      <td className="py-2 pr-3">{u.uniqueid ?? ""}</td>
                      <td className="py-2 pr-3">{u.is_admin ? t.roleAdmin : t.roleUser}</td>
                      <td className="py-2 pr-3">{u.is_admin ? t.allHotels : codes(u.hotel_ids)}</td>
                      <td className="py-2 pr-3">{u.active ? t.active : t.inactive}</td>
                      <td className="py-2 text-right">
                        <button className={button} aria-label={`${t.edit} ${u.name}`} onClick={() => { setNotice(null); setEditing(u); }}>
                          {t.edit}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {users.length === 0 && <p className="mt-4 text-sm text-stone-500">{t.noUsers}</p>}
            </div>
          </section>
        )
      ) : (
        <HotelsTable
          hotels={hotels}
          onSave={async (hotel, values) => {
            const saved = await api(`hotels/${hotel.id}`, "PATCH", values);
            if (saved) {
              setHotels((hs) => hs.map((h) => (h.id === saved.id ? saved : h)));
              setNotice(t.saved);
            }
          }}
        />
      )}
    </div>
  );
}

function UserForm({
  user,
  me,
  hotels,
  onCancel,
  onSubmit,
  onDelete,
}: {
  user: Account | null;
  me: Account;
  hotels: Hotel[];
  onCancel: () => void;
  onSubmit: (form: Form) => Promise<void>;
  onDelete?: () => Promise<void>;
}) {
  const { t } = useI18n();
  const [form, setForm] = useState<Form>(
    user
      ? {
          name: user.name, email: user.email, phone: user.phone ?? "", uniqueid: user.uniqueid ?? "",
          notes: user.notes ?? "", password: "", is_admin: user.is_admin, active: user.active, hotel_ids: user.hotel_ids,
        }
      : EMPTY,
  );
  const [busy, setBusy] = useState(false);
  const self = user?.id === me.id;
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));
  const text = (key: "name" | "email" | "phone" | "uniqueid", label: string, extra: object = {}) => (
    <label className="block text-sm">
      <span className="font-medium">{label}</span>
      <input name={key} value={form[key]} onChange={(e) => set(key, e.target.value)} className={input} {...extra} />
    </label>
  );

  return (
    <form
      className="mt-4 max-w-2xl space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        await onSubmit(form);
        setBusy(false);
      }}
    >
      <h2 className="text-base font-semibold">{user ? t.editUser : t.newUser}</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {text("name", t.fieldName, { required: true, maxLength: 200 })}
        {text("email", t.fieldEmail, { required: true, type: "email", maxLength: 254 })}
        {text("phone", t.fieldPhone, { type: "tel", maxLength: 40 })}
        {text("uniqueid", t.fieldUniqueId, { maxLength: 100 })}
      </div>
      <label className="block text-sm">
        <span className="font-medium">{t.fieldNotes}</span>
        <textarea name="notes" value={form.notes} onChange={(e) => set("notes", e.target.value)} rows={3} maxLength={2000} className={input} />
      </label>
      <label className="block text-sm">
        <span className="font-medium">{user ? t.newPasswordLabel : t.fieldPassword}</span>
        <input
          name="password"
          type="password"
          autoComplete="new-password"
          value={form.password}
          onChange={(e) => set("password", e.target.value)}
          required={!user}
          minLength={MIN_PASSWORD}
          maxLength={200}
          className={input}
        />
        <span className="mt-1 block text-xs text-stone-500">{t.passwordHint(MIN_PASSWORD)}</span>
      </label>

      <fieldset className="text-sm">
        <legend className="font-medium">{t.roleLabel}</legend>
        <label className="mt-1 flex items-center gap-2">
          <input type="checkbox" name="is_admin" checked={form.is_admin} disabled={self} onChange={(e) => set("is_admin", e.target.checked)} />
          {t.roleAdmin}
        </label>
        <span className="block text-xs text-stone-500">{t.adminHint}</span>
      </fieldset>
      <fieldset className="text-sm">
        <legend className="font-medium">{t.statusLabel}</legend>
        <label className="mt-1 flex items-center gap-2">
          <input type="checkbox" name="active" checked={form.active} disabled={self} onChange={(e) => set("active", e.target.checked)} />
          {t.active}
        </label>
      </fieldset>
      <fieldset className="text-sm">
        <legend className="font-medium">{t.hotelsLabel}</legend>
        {form.is_admin ? (
          <p className="mt-1 text-stone-500">{t.allHotels}</p>
        ) : (
          <>
            <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1">
              {hotels.map((h) => (
                <label key={h.id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    name="hotel"
                    value={h.code}
                    checked={form.hotel_ids.includes(h.id)}
                    onChange={(e) =>
                      set("hotel_ids", e.target.checked ? [...form.hotel_ids, h.id] : form.hotel_ids.filter((id) => id !== h.id))
                    }
                  />
                  {h.code} · {h.name}
                </label>
              ))}
            </div>
            {form.hotel_ids.length === 0 && <span className="mt-1 block text-xs text-amber-700 dark:text-amber-400">{t.noHotelsHint}</span>}
          </>
        )}
      </fieldset>

      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy} className={primary}>{t.save}</button>
        <button type="button" onClick={onCancel} className={button}>{t.cancel}</button>
        {onDelete && (
          <button
            type="button"
            onClick={onDelete}
            className="ml-auto rounded-lg px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
          >
            {t.deleteUser}
          </button>
        )}
      </div>
    </form>
  );
}

function HotelsTable({
  hotels,
  onSave,
}: {
  hotels: Hotel[];
  onSave: (hotel: Hotel, values: { alojamiento_id: number; pms_id: number }) => Promise<void>;
}) {
  const { t } = useI18n();
  return (
    <section className="mt-4">
      <p className="text-sm text-stone-500">{t.idHint}</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-stone-200 text-xs text-stone-500 dark:border-stone-800">
            <tr>
              <th className="py-2 pr-3 font-medium">{t.colCode}</th>
              <th className="py-2 pr-3 font-medium">{t.colHotel}</th>
              <th className="py-2 pr-3 font-medium">{t.colCity}</th>
              <th className="py-2 pr-3 font-medium">{t.alojamientoId}</th>
              <th className="py-2 pr-3 font-medium">{t.pmsId}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {hotels.map((h) => (
              <HotelRow key={`${h.id}-${h.alojamiento_id}-${h.pms_id}`} hotel={h} onSave={onSave} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const validId = (value: string) => /^[1-9][0-9]{0,9}$/.test(value) && Number(value) <= MAX_ID;

function HotelRow({
  hotel,
  onSave,
}: {
  hotel: Hotel;
  onSave: (hotel: Hotel, values: { alojamiento_id: number; pms_id: number }) => Promise<void>;
}) {
  const { t } = useI18n();
  const [alojamiento, setAlojamiento] = useState(String(hotel.alojamiento_id));
  const [pms, setPms] = useState(String(hotel.pms_id));
  const changed = alojamiento !== String(hotel.alojamiento_id) || pms !== String(hotel.pms_id);
  const valid = validId(alojamiento) && validId(pms);
  const field = (label: string, value: string, onChange: (v: string) => void) => (
    <input
      aria-label={`${label} ${hotel.code}`}
      inputMode="numeric"
      value={value}
      onChange={(e) => onChange(e.target.value.trim())}
      aria-invalid={!validId(value)}
      title={validId(value) ? undefined : t.invalidId}
      className={`w-28 rounded-lg border bg-white px-2 py-1 outline-none focus:border-accent dark:bg-stone-900 ${validId(value) ? "border-stone-300 dark:border-stone-700" : "border-red-500"}`}
    />
  );
  return (
    <tr className="border-b border-stone-100 dark:border-stone-900">
      <td className="py-2 pr-3 font-medium">{hotel.code}</td>
      <td className="py-2 pr-3">{hotel.name}</td>
      <td className="py-2 pr-3">{hotel.city}</td>
      <td className="py-2 pr-3">{field(t.alojamientoId, alojamiento, setAlojamiento)}</td>
      <td className="py-2 pr-3">{field(t.pmsId, pms, setPms)}</td>
      <td className="py-2 text-right">
        <button
          className={primary}
          disabled={!changed || !valid}
          aria-label={`${t.save} ${hotel.code}`}
          onClick={() => onSave(hotel, { alojamiento_id: Number(alojamiento), pms_id: Number(pms) })}
        >
          {t.save}
        </button>
      </td>
    </tr>
  );
}
