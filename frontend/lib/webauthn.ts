"use client";

function base64urlToUint8Array(value: string): Uint8Array {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
  const binary = window.atob(padded);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function arrayBufferToBase64url(buffer: ArrayBuffer | ArrayBufferLike): string {
  const bytes = buffer instanceof ArrayBuffer ? new Uint8Array(buffer) : new Uint8Array(buffer.slice(0));
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function normalizeCreationOptions(publicKey: Record<string, unknown>): PublicKeyCredentialCreationOptions {
  const data = publicKey as {
    challenge: string;
    rp: PublicKeyCredentialRpEntity;
    user: { id: string; name: string; displayName: string };
    pubKeyCredParams: PublicKeyCredentialParameters[];
    timeout?: number;
    excludeCredentials?: Array<{ id: string; type: PublicKeyCredentialType; transports?: AuthenticatorTransport[] }>;
    authenticatorSelection?: AuthenticatorSelectionCriteria;
    attestation?: AttestationConveyancePreference;
  };
  return {
    challenge: base64urlToUint8Array(data.challenge),
    rp: data.rp,
    user: {
      id: base64urlToUint8Array(data.user.id),
      name: data.user.name,
      displayName: data.user.displayName,
    },
    pubKeyCredParams: data.pubKeyCredParams,
    timeout: data.timeout,
    authenticatorSelection: data.authenticatorSelection,
    attestation: data.attestation,
    excludeCredentials: data.excludeCredentials?.map((item) => ({
      ...item,
      id: base64urlToUint8Array(item.id),
    })),
  };
}

function normalizeAssertionOptions(publicKey: Record<string, unknown>): PublicKeyCredentialRequestOptions {
  const data = publicKey as {
    challenge: string;
    rpId: string;
    timeout?: number;
    allowCredentials?: Array<{ id: string; type: PublicKeyCredentialType; transports?: AuthenticatorTransport[] }>;
    userVerification?: UserVerificationRequirement;
  };
  return {
    challenge: base64urlToUint8Array(data.challenge),
    rpId: data.rpId,
    timeout: data.timeout,
    userVerification: data.userVerification,
    allowCredentials: data.allowCredentials?.map((item) => ({
      ...item,
      id: base64urlToUint8Array(item.id),
    })),
  };
}

export function browserSupportsPasskeys(): boolean {
  return typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials;
}

export async function createPasskeyCredential(publicKey: Record<string, unknown>) {
  const credential = (await navigator.credentials.create({
    publicKey: normalizeCreationOptions(publicKey),
  })) as PublicKeyCredential | null;
  if (!credential) {
    throw new Error("Passkey-Erstellung wurde abgebrochen");
  }
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: arrayBufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: arrayBufferToBase64url(response.clientDataJSON),
      attestationObject: arrayBufferToBase64url(response.attestationObject),
      transports: typeof response.getTransports === "function" ? response.getTransports() : [],
    },
  };
}

export async function getPasskeyAssertion(publicKey: Record<string, unknown>) {
  const credential = (await navigator.credentials.get({
    publicKey: normalizeAssertionOptions(publicKey),
  })) as PublicKeyCredential | null;
  if (!credential) {
    throw new Error("Passkey-Anmeldung wurde abgebrochen");
  }
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: arrayBufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: arrayBufferToBase64url(response.clientDataJSON),
      authenticatorData: arrayBufferToBase64url(response.authenticatorData),
      signature: arrayBufferToBase64url(response.signature),
      userHandle: response.userHandle ? arrayBufferToBase64url(response.userHandle) : null,
    },
  };
}
