"use client";

import { useEffect, useState } from "react";
import {
  getSettings,
  refreshSettings,
  subscribe,
  type PlatformSettings,
} from "@/lib/platformSettings";

export function usePlatformSettings(): {
  settings: PlatformSettings | null;
  reload: () => void;
} {
  const [settings, setSettings] = useState<PlatformSettings | null>(getSettings());

  useEffect(() => {
    const sync = () => setSettings(getSettings());
    const unsubscribe = subscribe(sync);
    refreshSettings();
    return unsubscribe;
  }, []);

  return { settings, reload: () => void refreshSettings() };
}

export function usePlatformName(): string {
  const { settings } = usePlatformSettings();
  return settings?.platform_name || "Synapse";
}
