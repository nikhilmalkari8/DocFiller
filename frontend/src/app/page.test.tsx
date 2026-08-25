import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import Home from "./page";

beforeEach(() => {
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const UPLOAD_RESPONSE = {
  session_id: "session-123",
  excel_columns: ["Name", "Date"],
  excel_preview: [
    { Name: "John Doe", Date: "2024-01-15" },
    { Name: "Jane Smith", Date: "2024-02-20" },
    { Name: "Ann Lee", Date: "2024-03-01" },
  ],
  total_rows: 3,
  placeholders: ["Name", "Date"],
  template_type: "pdf",
};

const MAP_RESPONSE = { mapping: { Name: "Name", Date: "Date" } };

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 400) {
  return {
    ok,
    status,
    json: async () => body,
    headers: { get: () => null },
  } as unknown as Response;
}

function stubFetchSequence(responses: Array<() => Response | Promise<Response>>) {
  let call = 0;
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) => {
      const next = responses[Math.min(call, responses.length - 1)];
      call += 1;
      return next();
    }
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function uploadFile(input: HTMLInputElement, file: File) {
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

async function renderAndUpload(options?: { templateType?: "pdf" | "word" }) {
  const templateType = options?.templateType ?? "pdf";
  const fetchMock = stubFetchSequence([
    () => jsonResponse({ ...UPLOAD_RESPONSE, template_type: templateType }),
    () => jsonResponse(MAP_RESPONSE),
  ]);

  render(<Home />);

  const excelInput = document.querySelector(
    'input[accept=".xlsx,.xls,.xlsm"]'
  ) as HTMLInputElement;
  const templateInput = document.querySelector(
    'input[accept=".pdf,.docx,.docm"]'
  ) as HTMLInputElement;

  const excelFile = new File(["excel"], "data.xlsx", {
    type: "application/vnd.ms-excel",
  });
  const templateExt = templateType === "word" ? "docm" : "pdf";
  const templateFile = new File(["template"], `template.${templateExt}`, {
    type: "application/octet-stream",
  });

  uploadFile(excelInput, excelFile);
  uploadFile(templateInput, templateFile);
  fireEvent.click(screen.getByRole("button", { name: /Upload & Analyze/i }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

  return { fetchMock };
}

describe("Home smoke test", () => {
  test("renders the DocFiller heading", () => {
    render(<Home />);
    expect(
      screen.getByRole("heading", { level: 1, name: "DocFiller" })
    ).toBeDefined();
  });
});

describe("setup modal", () => {
  test("opens after Upload & Analyze, before the mapping table renders", async () => {
    await renderAndUpload();
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
  });

  test("shows a combobox listing every Excel column, defaulting to the first", async () => {
    await renderAndUpload();
    const combobox = screen.getByRole("combobox") as HTMLSelectElement;
    const optionLabels = Array.from(combobox.options).map((o) => o.value);
    expect(optionLabels).toContain("Name");
    expect(optionLabels).toContain("Date");
    expect(combobox.value).toBe("Name");
  });

  test("helper text shows the resulting filename and updates on column change", async () => {
    await renderAndUpload();
    expect(screen.getByText(/John_Doe\.pdf/i)).toBeDefined();

    const combobox = screen.getByRole("combobox") as HTMLSelectElement;
    fireEvent.change(combobox, { target: { value: "Date" } });

    expect(screen.getByText(/2024-01-15\.pdf/i)).toBeDefined();
  });

  test("Continue closes the dialog and reveals the mapping table", async () => {
    await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("table")).toBeDefined();
  });

  test("Skip closes the dialog and reveals the mapping table", async () => {
    await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Skip/i }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("table")).toBeDefined();
  });

  test("after continuing, the Review step shows the chosen naming column with a Change button", async () => {
    await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));

    const namingLine = screen.getByText(/Naming documents by:/i);
    expect(namingLine.closest(".row-selector")?.textContent).toContain("Name");

    fireEvent.click(screen.getByRole("button", { name: /Change/i }));
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  test("Escape closes the dialog", async () => {
    await renderAndUpload();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

const GENERATE_ALL_RESPONSE = {
  total_rows: 3,
  success_count: 2,
  error_count: 1,
  skipped_count: 0,
  results: [
    {
      row_index: 0,
      status: "ok",
      label: "John Doe",
      filename: "John_Doe.pdf",
      mime_type: "application/pdf",
      content_base64: "JVBERi0=",
      error: null,
    },
    {
      row_index: 1,
      status: "error",
      label: "Jane Smith",
      filename: null,
      mime_type: null,
      content_base64: null,
      error: "Failed to fill template",
    },
    {
      row_index: 2,
      status: "ok",
      label: "Ann Lee",
      filename: "Ann_Lee.pdf",
      mime_type: "application/pdf",
      content_base64: "JVBERi1=",
      error: null,
    },
  ],
};

describe("bulk generate all rows", () => {
  test("Review shows a Generate All Rows button alongside Generate Document", async () => {
    await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));

    expect(screen.getByRole("button", { name: /Generate Document/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /Generate All Rows \(3\)/i })).toBeDefined();
  });

  test("clicking Generate All Rows POSTs once to /api/generate-all with session_id, mapping, filename_column, no row_index", async () => {
    const { fetchMock } = await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));

    fetchMock.mockImplementationOnce(async () => jsonResponse(GENERATE_ALL_RESPONSE));
    fireEvent.click(screen.getByRole("button", { name: /Generate All Rows/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    const call = fetchMock.mock.calls[2];
    expect(String(call[0])).toMatch(/\/api\/generate-all$/);
    const body = JSON.parse((call[1] as RequestInit).body as string);
    expect(body.session_id).toBe("session-123");
    expect(body.mapping).toBeDefined();
    expect(body.filename_column).toBe("Name");
    expect(body.row_index).toBeUndefined();
  });

  test("a mixed success/error response renders one row per result, downloads only for ok rows, and a summary", async () => {
    const { fetchMock } = await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
    fetchMock.mockImplementationOnce(async () => jsonResponse(GENERATE_ALL_RESPONSE));
    fireEvent.click(screen.getByRole("button", { name: /Generate All Rows/i }));

    await waitFor(() =>
      expect(screen.getByText(/2 of 3/i)).toBeDefined()
    );

    expect(screen.getAllByRole("row")).toHaveLength(4); // header + 3 results
    expect(screen.getAllByRole("button", { name: /^📥 Download$/ })).toHaveLength(2);
    expect(screen.getByText("Failed to fill template")).toBeDefined();
  });

  test("clicking a row's Download calls createObjectURL once with that result's filename", async () => {
    const { fetchMock } = await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
    fetchMock.mockImplementationOnce(async () => jsonResponse(GENERATE_ALL_RESPONSE));
    fireEvent.click(screen.getByRole("button", { name: /Generate All Rows/i }));
    await waitFor(() => expect(screen.getByText(/2 of 3/i)).toBeDefined());

    const downloadButtons = screen.getAllByRole("button", { name: /^📥 Download$/ });
    fireEvent.click(downloadButtons[0]);

    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  test("Download All produces one createObjectURL call for a zip blob", async () => {
    const { fetchMock } = await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
    fetchMock.mockImplementationOnce(async () => jsonResponse(GENERATE_ALL_RESPONSE));
    fireEvent.click(screen.getByRole("button", { name: /Generate All Rows/i }));
    await waitFor(() => expect(screen.getByText(/2 of 3/i)).toBeDefined());

    fireEvent.click(screen.getByRole("button", { name: /Download All \(2\)/i }));

    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
  });

  test("regenerating a single document after a prior bulk run does not show stale bulk results", async () => {
    const { fetchMock } = await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
    fetchMock.mockImplementationOnce(async () => jsonResponse(GENERATE_ALL_RESPONSE));
    fireEvent.click(screen.getByRole("button", { name: /Generate All Rows/i }));
    await waitFor(() => expect(screen.getByText(/2 of 3/i)).toBeDefined());

    // Back to mapping, then generate a single document
    fireEvent.click(screen.getByRole("button", { name: /Back to Mapping/i }));
    fetchMock.mockImplementationOnce(
      async () =>
        ({
          ok: true,
          status: 200,
          blob: async () => new Blob(["pdf-bytes"]),
          headers: { get: () => 'attachment; filename="John_Doe.pdf"' },
        }) as unknown as Response
    );
    fireEvent.click(screen.getByRole("button", { name: /^✨ Generate Document$/ }));

    await waitFor(() => expect(screen.getByText(/Document Ready/i)).toBeDefined());
    expect(screen.queryByText(/2 of 3/i)).toBeNull();
  });

  test("Skip resets the naming column so fallback row numbering applies", async () => {
    const { fetchMock } = await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Skip/i }));

    fetchMock.mockImplementationOnce(async () => jsonResponse(GENERATE_ALL_RESPONSE));
    fireEvent.click(screen.getByRole("button", { name: /Generate All Rows/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    const call = fetchMock.mock.calls[2];
    const body = JSON.parse((call[1] as RequestInit).body as string);
    expect(body.filename_column).toBeUndefined();
  });

  test("a non-200 /api/generate-all response shows the error banner and stays on Review", async () => {
    const { fetchMock } = await renderAndUpload();
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
    fetchMock.mockImplementationOnce(async () =>
      jsonResponse({ detail: "Bulk generation failed" }, false, 500)
    );
    fireEvent.click(screen.getByRole("button", { name: /Generate All Rows/i }));

    await waitFor(() =>
      expect(screen.getByText("Bulk generation failed")).toBeDefined()
    );
    expect(screen.getByRole("table")).toBeDefined(); // still the mapping table, not results
  });
});
