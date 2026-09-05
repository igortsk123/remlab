// <model-viewer> (Google, вендорен в public/vendor/model-viewer.min.js) как JSX-элемент.
// Только атрибуты, которые используются на /lab/mesh-audit.
import type { DetailedHTMLProps, HTMLAttributes } from "react";

type ModelViewerAttributes = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
  src?: string;
  poster?: string;
  alt?: string;
  "camera-controls"?: boolean | "";
  "auto-rotate"?: boolean | "";
  "shadow-intensity"?: string;
  loading?: "auto" | "lazy" | "eager";
  reveal?: "auto" | "manual";
};

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "model-viewer": ModelViewerAttributes;
    }
  }
}
