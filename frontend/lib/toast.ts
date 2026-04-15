import { toast } from "sonner";

export function showSuccess(message: string, description?: string) {
  toast.success(message, { description });
}

export function showError(message: string, description?: string) {
  toast.error(message, { description });
}

export function showInfo(message: string, description?: string) {
  toast.info(message, { description });
}

export function showLoading(message: string) {
  return toast.loading(message);
}

export function dismissToast(id: string | number) {
  toast.dismiss(id);
}
