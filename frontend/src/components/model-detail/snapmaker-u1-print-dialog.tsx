"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Modal } from "@/components/ui/modal";
import { getSnapmakerU1Preflight } from "@/lib/api/printers";
import type { SnapmakerU1Preflight, SnapmakerU1Start } from "@/types/printers";

function baseMaterial(value: string | null): string | null {
  return value?.trim().split(/[ _-]/)[0]?.toUpperCase() ?? null;
}

function autoMapping(data: SnapmakerU1Preflight): [number, number][] {
  const available = new Set(data.slots.filter((slot) => slot.present).map((slot) => slot.index));
  return data.filaments.flatMap((filament) => {
    const candidates = [...available];
    const selected =
      candidates.find((index) => {
        const slot = data.slots[index];
        return (
          baseMaterial(slot.material) === baseMaterial(filament.material) &&
          slot.color?.toUpperCase() === filament.color?.toUpperCase()
        );
      }) ??
      candidates.find((index) => baseMaterial(data.slots[index].material) === baseMaterial(filament.material)) ??
      candidates[0];
    if (selected === undefined) return [];
    available.delete(selected);
    return [[filament.index, selected] as [number, number]];
  });
}

export function SnapmakerU1PrintDialog({
  printerId,
  fileId,
  filename,
  onClose,
  onStart,
  loadPreflight = getSnapmakerU1Preflight,
}: {
  printerId: number;
  fileId: number;
  filename: string;
  onClose: () => void;
  onStart: (settings: SnapmakerU1Start) => Promise<void>;
  loadPreflight?: typeof getSnapmakerU1Preflight;
}) {
  const [data, setData] = useState<SnapmakerU1Preflight | null>(null);
  const [mapping, setMapping] = useState<[number, number][]>([]);
  const [bedLevel, setBedLevel] = useState(true);
  const [flowCalibrate, setFlowCalibrate] = useState(false);
  const [timelapse, setTimelapse] = useState(false);
  const [allowMismatch, setAllowMismatch] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const response = await loadPreflight(printerId, fileId);
      setData(response);
      setMapping(autoMapping(response));
      setAllowMismatch(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to read toolhead filaments");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let current = true;
    void loadPreflight(printerId, fileId)
      .then((response) => {
        if (!current) return;
        setData(response);
        setMapping(autoMapping(response));
      })
      .catch((reason) => {
        if (current) setError(reason instanceof Error ? reason.message : "Unable to read U1 filament state");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [fileId, printerId, loadPreflight]);

  const warnings = useMemo(() => {
    if (!data) return [];
    return data.filaments.flatMap((filament) => {
      const headIndex = mapping.find(([tool]) => tool === filament.index)?.[1];
      const head = data.slots.find((slot) => slot.index === headIndex);
      if (!head) return [`T${filament.index}: select a toolhead`];
      if (!head.present) return [`Head ${head.index + 1} has no loaded filament`];
      const out: string[] = [];
      if (
        filament.material &&
        head.material &&
        baseMaterial(filament.material) !== baseMaterial(head.material)
      ) {
        out.push(`T${filament.index} requires ${filament.material}; head ${head.index + 1} has ${head.material}`);
      }
      if (filament.color && head.color && filament.color.toUpperCase() !== head.color.toUpperCase()) {
        out.push(`T${filament.index} color differs from head ${head.index + 1}`);
      }
      return out;
    });
  }, [data, mapping]);

  const materialMismatch =
    data?.filaments.some((filament) => {
      const head = data.slots.find(
        (slot) => slot.index === mapping.find(([tool]) => tool === filament.index)?.[1],
      );
      return (
        head?.present &&
        filament.material &&
        head.material &&
        baseMaterial(filament.material) !== baseMaterial(head.material)
      );
    }) ?? false;

  const complete =
    data !== null &&
    data.filaments.length > 0 &&
    data.filaments.length <= 4 &&
    mapping.length === data.filaments.length &&
    new Set(mapping.map(([, head]) => head)).size === mapping.length &&
    mapping.every(([, head]) => data.slots.some((slot) => slot.index === head && slot.present));

  async function start() {
    if (!complete || (materialMismatch && !allowMismatch) || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onStart({
        mapping,
        options: {
          bed_level: bedLevel,
          flow_calibrate: flowCalibrate,
          time_lapse_camera: timelapse,
        },
        allow_material_mismatch: allowMismatch,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Print-start outcome unknown. Inspect printer before retrying.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={() => { if (!busy) onClose(); }}
      title={`Snapmaker U1 · ${filename}`}
      className="max-w-4xl"
    >
      <p className="mb-4 text-sm text-muted-foreground">
        Map each sliced filament to one of the four currently loaded toolheads.
      </p>
      {loading && <p role="status" className="text-sm text-muted-foreground">Reading toolhead filaments…</p>}
      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {data.filaments.map((filament) => {
              const selected = mapping.find(([tool]) => tool === filament.index)?.[1];
              const head = data.slots.find((slot) => slot.index === selected);
              return (
                <section key={filament.index} className="rounded-lg border border-border bg-background p-3">
                  <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
                    <span className="h-4 w-4 rounded-full border border-border" style={{ backgroundColor: filament.color ?? "transparent" }} />
                    T{filament.index} · {filament.material ?? "Unknown material"}
                  </div>
                  {filament.grams != null && (
                    <p className="mb-3 text-xs text-muted-foreground">{filament.grams.toFixed(1)} g</p>
                  )}
                  <label htmlFor={`u1-head-${filament.index}`} className="text-xs text-muted-foreground">
                    Physical toolhead
                  </label>
                  <select
                    id={`u1-head-${filament.index}`}
                    className="mt-1 w-full rounded-md border border-input bg-background p-2 text-sm"
                    value={selected ?? ""}
                    disabled={busy || loading}
                    onChange={(event) => {
                      const next = Number(event.target.value);
                      setMapping((current) => [
                        ...current.filter(([tool]) => tool !== filament.index),
                        ...(event.target.value ? [[filament.index, next] as [number, number]] : []),
                      ]);
                      setAllowMismatch(false);
                    }}
                  >
                    <option value="">Choose head…</option>
                    {data.slots.map((slot) => (
                      <option
                        key={slot.index}
                        value={slot.index}
                        disabled={
                          !slot.present ||
                          mapping.some(([tool, index]) => tool !== filament.index && index === slot.index)
                        }
                      >
                        Head {slot.index + 1} · {slot.vendor ?? ""} {slot.material ?? (slot.present ? "Unknown" : "Empty")}
                      </option>
                    ))}
                  </select>
                  {head && (
                    <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="h-7 w-7 rounded-full border border-border" style={{ backgroundColor: head.color ?? "transparent" }} />
                      <span>{head.vendor ?? "Unknown vendor"} · {head.subtype ?? head.material ?? "Unknown"}</span>
                    </div>
                  )}
                </section>
              );
            })}
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-4">
            {data.slots.map((slot) => (
              <div key={slot.index} className="flex items-center gap-2 rounded-md border border-border p-2 text-xs">
                <span className="h-5 w-5 shrink-0 rounded-full border border-border" style={{ backgroundColor: slot.color ?? "transparent" }} />
                <span>Head {slot.index + 1} · {slot.present ? (slot.material ?? "Unknown") : "Empty"}</span>
              </div>
            ))}
          </div>
          {warnings.length > 0 && (
            <div role="status" className="mt-4 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
              <p className="font-semibold">Mapping warnings</p>
              <ul className="mt-2 list-inside list-disc text-xs">
                {warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
              {materialMismatch && (
                <label className="mt-3 flex items-center gap-2">
                  <Checkbox checked={allowMismatch} onChange={setAllowMismatch} />
                  <span>I verified the material mismatch; print anyway</span>
                </label>
              )}
            </div>
          )}
          <fieldset className="mt-5 border-t border-border pt-4">
            <legend className="text-sm font-semibold">Print preferences</legend>
            <div className="mt-2 flex flex-wrap gap-4 text-sm">
              <label className="flex items-center gap-2"><Checkbox checked={bedLevel} onChange={setBedLevel} />Auto bed leveling</label>
              <label className="flex items-center gap-2"><Checkbox checked={flowCalibrate} onChange={setFlowCalibrate} />Dynamic flow calibration</label>
              <label className="flex items-center gap-2"><Checkbox checked={timelapse} onChange={setTimelapse} />Timelapse</label>
            </div>
          </fieldset>
        </>
      )}
      {error && <p role="alert" className="mt-4 text-sm text-destructive">{error}</p>}
      <div className="mt-5 flex justify-between gap-2 border-t border-border pt-4">
        <Button variant="outline" onClick={() => void refresh()} disabled={loading || busy}>Refresh filaments</Button>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={() => void start()} loading={busy} disabled={!complete || loading || busy || (materialMismatch && !allowMismatch)}>
            Send & start print
          </Button>
        </div>
      </div>
    </Modal>
  );
}
