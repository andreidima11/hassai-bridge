import { useState } from "react";
import { ImageLightbox } from "./ImageLightbox.jsx";
import { tr } from "../lib/i18n.js";

export function ChatImage({
  src,
  alt = "",
  className = "",
  wrapperClassName = "",
  filename = "",
  mime = "",
  lang = "en",
}) {
  const [open, setOpen] = useState(false);
  if (!src) return null;

  return (
    <>
      <button
        type="button"
        className={`block max-w-full cursor-zoom-in rounded-[inherit] border-0 bg-transparent p-0 text-left ${wrapperClassName}`.trim()}
        aria-label={tr(lang, "enlargeImage")}
        title={tr(lang, "enlargeImage")}
        onClick={() => setOpen(true)}
      >
        <img alt={alt || ""} className={`block ${className}`.trim()} src={src} />
      </button>
      {open ? (
        <ImageLightbox
          alt={alt}
          filename={filename}
          lang={lang}
          mime={mime}
          src={src}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}
