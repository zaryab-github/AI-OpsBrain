import { Construction } from "lucide-react";
import { useLocation } from "react-router-dom";

import { useModules } from "../api/hooks";
import { Card, PageHeader } from "../components/ui";
import { findNav } from "../layout/nav";

/**
 * Shown for navigation entries whose feature has not been implemented yet.
 * It deliberately shows no numbers or sample content — only what is true about the platform.
 */
export default function NotYetBuilt() {
  const location = useLocation();
  const match = findNav(location.pathname);
  const modules = useModules();
  if (!match) return null;
  const { section, item } = match;
  const mod = section.module ? modules.data?.modules.find((m) => m.key === section.module) : undefined;
  return (
    <>
      <PageHeader title={item.label} description={section.label} />
      <Card>
        <div className="flex items-start gap-3">
          <Construction className="mt-0.5 h-5 w-5 text-amber-600" aria-hidden />
          <div className="space-y-2 text-sm text-slate-700">
            <p>
              <strong>{item.label}</strong> is not available in this release yet
              {item.phase ? <> — it is scheduled for build phase {item.phase}.</> : "."}
            </p>
            {mod && !mod.installed && (
              <p>
                The <strong>{mod.name}</strong> server module is not installed. Once available, install it on the
                platform server with <code className="rounded bg-slate-100 px-1">sudo opsbrainctl install {mod.key}</code>.
              </p>
            )}
          </div>
        </div>
      </Card>
    </>
  );
}
