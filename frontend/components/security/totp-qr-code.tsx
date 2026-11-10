"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { useTranslations } from "next-intl";

type Props = {
  value: string;
  size?: number;
};

export function TotpQrCode({ value, size = 196 }: Props) {
  const t = useTranslations("security");
  const [dataUrl, setDataUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDataUrl(null);
    QRCode.toDataURL(value, { width: size * 2, margin: 1, errorCorrectionLevel: "M" })
      .then((url) => {
        if (!cancelled) setDataUrl(url);
      })
      .catch(() => {
        if (!cancelled) setDataUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [value, size]);

  return (
    <div className="totp-qr-frame" style={{ width: size, height: size }}>
      {dataUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={dataUrl} alt={t("qrCodeAlt")} width={size} height={size} />
      ) : (
        <div className="totp-qr-placeholder" aria-hidden="true" />
      )}
    </div>
  );
}
