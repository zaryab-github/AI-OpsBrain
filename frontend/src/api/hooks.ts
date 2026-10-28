import { useQuery } from "@tanstack/react-query";

import { get } from "./client";
import type { ModuleInfo } from "./types";

export function useModules() {
  return useQuery({
    queryKey: ["system", "modules"],
    queryFn: () => get<{ version: string; modules: ModuleInfo[] }>("/system/modules"),
    staleTime: 60_000,
  });
}

export function usePlatformName(): string {
  const { data } = useQuery({
    queryKey: ["settings", "public"],
    queryFn: () => get<{ platform_name: string }>("/settings/public"),
    staleTime: 300_000,
  });
  return data?.platform_name ?? "AI-OpsBrain";
}
