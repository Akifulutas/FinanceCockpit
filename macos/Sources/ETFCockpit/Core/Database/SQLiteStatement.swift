import Foundation
import SQLite3

public final class SQLiteStatement {
    private var stmt: OpaquePointer?
    private let sql: String

    public enum StatementError: Error, LocalizedError {
        case prepareFailed(query: String, code: Int32, message: String)
        case stepFailed(code: Int32, message: String)
        case bindFailed(index: Int32, code: Int32, message: String)
        case finalized

        public var errorDescription: String? {
            switch self {
            case .prepareFailed(let q, let code, let msg):
                return "Query preparation failed (\(code)): \(q) — \(msg)"
            case .stepFailed(let code, let msg):
                return "Query execution error (\(code)): \(msg)"
            case .bindFailed(let idx, let code, let msg):
                return "Parameter binding error (index \(idx), code \(code)): \(msg)"
            case .finalized:
                return "Statement already finalized."
            }
        }
    }

    public init(db: OpaquePointer?, sql: String) throws {
        self.sql = sql
        var statementPointer: OpaquePointer?
        let rc = sqlite3_prepare_v2(db, sql, -1, &statementPointer, nil)
        guard rc == SQLITE_OK, let statementPointer else {
            let msg = db != nil ? String(cString: sqlite3_errmsg(db)) : "Unknown DB error"
            throw StatementError.prepareFailed(query: sql, code: rc, message: msg)
        }
        self.stmt = statementPointer
    }

    deinit {
        if let stmt = stmt {
            sqlite3_finalize(stmt)
        }
    }

    // MARK: - Bindings (1-based index)

    public func bindText(_ text: String?, at index: Int32) throws {
        guard let stmt = stmt else { throw StatementError.finalized }
        let rc: Int32
        if let text = text {
            rc = sqlite3_bind_text(stmt, index, NSString(string: text).utf8String, -1, nil)
        } else {
            rc = sqlite3_bind_null(stmt, index)
        }
        guard rc == SQLITE_OK else {
            throw StatementError.bindFailed(index: index, code: rc, message: "bindText failed")
        }
    }

    public func bindInt(_ value: Int32, at index: Int32) throws {
        guard let stmt = stmt else { throw StatementError.finalized }
        let rc = sqlite3_bind_int(stmt, index, value)
        guard rc == SQLITE_OK else {
            throw StatementError.bindFailed(index: index, code: rc, message: "bindInt failed")
        }
    }

    public func bindInt64(_ value: Int64, at index: Int32) throws {
        guard let stmt = stmt else { throw StatementError.finalized }
        let rc = sqlite3_bind_int64(stmt, index, value)
        guard rc == SQLITE_OK else {
            throw StatementError.bindFailed(index: index, code: rc, message: "bindInt64 failed")
        }
    }

    public func bindDouble(_ value: Double, at index: Int32) throws {
        guard let stmt = stmt else { throw StatementError.finalized }
        let rc = sqlite3_bind_double(stmt, index, value)
        guard rc == SQLITE_OK else {
            throw StatementError.bindFailed(index: index, code: rc, message: "bindDouble failed")
        }
    }

    public func bindNull(at index: Int32) throws {
        guard let stmt = stmt else { throw StatementError.finalized }
        let rc = sqlite3_bind_null(stmt, index)
        guard rc == SQLITE_OK else {
            throw StatementError.bindFailed(index: index, code: rc, message: "bindNull failed")
        }
    }

    // MARK: - Stepping

    public func step() throws -> Int32 {
        guard let stmt = stmt else { throw StatementError.finalized }
        let rc = sqlite3_step(stmt)
        if rc != SQLITE_ROW && rc != SQLITE_DONE {
            throw StatementError.stepFailed(code: rc, message: "sqlite3_step failed with code \(rc)")
        }
        return rc
    }

    public func reset() {
        if let stmt = stmt {
            sqlite3_reset(stmt)
        }
    }

    // MARK: - Column Extraction (0-based index)

    public var columnCount: Int32 {
        guard let stmt = stmt else { return 0 }
        return sqlite3_column_count(stmt)
    }

    public func columnName(at index: Int32) -> String {
        guard let stmt = stmt, let name = sqlite3_column_name(stmt, index) else { return "" }
        return String(cString: name)
    }

    public func columnIsNull(at index: Int32) -> Bool {
        guard let stmt = stmt else { return true }
        return sqlite3_column_type(stmt, index) == SQLITE_NULL
    }

    public func columnText(at index: Int32) -> String? {
        guard let stmt = stmt, !columnIsNull(at: index) else { return nil }
        guard let cString = sqlite3_column_text(stmt, index) else { return nil }
        return String(cString: cString)
    }

    public func columnCleanText(at index: Int32) -> String? {
        guard let text = columnText(at: index) else { return nil }
        return text.trimmingCharacters(in: CharacterSet(charactersIn: "'\" \t\r\n"))
    }

    public func columnDecimal(at index: Int32) -> Decimal? {
        guard let text = columnText(at: index) else { return nil }
        return Formatters.parseDecimal(from: text)
    }

    public func columnDouble(at index: Int32) -> Double? {
        guard let stmt = stmt, !columnIsNull(at: index) else { return nil }
        // If stored as text (e.g. Decimal string with single quotes)
        if sqlite3_column_type(stmt, index) == SQLITE_TEXT {
            if let decimal = columnDecimal(at: index) {
                return NSDecimalNumber(decimal: decimal).doubleValue
            }
        }
        return sqlite3_column_double(stmt, index)
    }

    public func columnInt(at index: Int32) -> Int? {
        guard let stmt = stmt, !columnIsNull(at: index) else { return nil }
        if sqlite3_column_type(stmt, index) == SQLITE_TEXT {
            if let clean = columnCleanText(at: index) {
                return Int(clean)
            }
        }
        return Int(sqlite3_column_int(stmt, index))
    }

    public func columnInt64(at index: Int32) -> Int64? {
        guard let stmt = stmt, !columnIsNull(at: index) else { return nil }
        if sqlite3_column_type(stmt, index) == SQLITE_TEXT {
            if let clean = columnCleanText(at: index) {
                return Int64(clean)
            }
        }
        return sqlite3_column_int64(stmt, index)
    }

    public func columnBool(at index: Int32) -> Bool? {
        guard let stmt = stmt, !columnIsNull(at: index) else { return nil }
        if sqlite3_column_type(stmt, index) == SQLITE_INTEGER {
            return sqlite3_column_int(stmt, index) != 0
        }
        if let clean = columnCleanText(at: index)?.lowercased() {
            if clean == "true" || clean == "1" || clean == "t" { return true }
            if clean == "false" || clean == "0" || clean == "f" { return false }
        }
        return nil
    }
}
