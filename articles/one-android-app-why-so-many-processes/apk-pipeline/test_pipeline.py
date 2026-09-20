import pathlib
import tempfile
import unittest
import zipfile
from pipeline import manifest_model, apk_inventory, require_arm64


class ManifestTests(unittest.TestCase):
    def test_arm64_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'input.apk'
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('lib/armeabi-v7a/libtest.so',b'32bit')
            with self.assertRaises(ValueError): require_arm64([path])
            header=bytearray(20)
            header[:6]=b'\x7fELF\x02\x01'
            header[18:20]=(183).to_bytes(2,'little')
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('lib/arm64-v8a/libtest.so',header)
                archive.writestr('lib/arm64-v8a/libplaceholder.so',b'not an ELF')
            result=require_arm64([path])
            self.assertEqual(result['verified_aarch64_libraries'],1)
            self.assertEqual(result['non_elf_arm64_entries'][0]['entry'],'lib/arm64-v8a/libplaceholder.so')

    def parse(self, body):
        return manifest_model('<manifest package="com.test" xmlns:android="http://schemas.android.com/apk/res/android">'+body+'</manifest>')['components']

    def test_defaults_and_private_process(self):
        rows=self.parse('<application><activity android:name=".Main"/><service android:name="Worker" android:process=":worker" android:isolatedProcess="true"/></application>')
        self.assertEqual(rows[0]['effective_process'],'com.test')
        self.assertEqual(rows[1]['effective_process'],'com.test:worker')
        self.assertEqual(rows[1]['attributes']['isolatedProcess'],'true')
        self.assertIsNone(rows[0]['exported'])

    def test_application_inheritance(self):
        rows=self.parse('<application android:process=":all"><provider android:name=".P"/></application>')
        self.assertEqual(rows[0]['effective_process'],'com.test:all')

    def test_disabled_application_cannot_be_overridden(self):
        rows=self.parse('<application android:enabled="false"><service android:name=".S" android:enabled="true"/></application>')
        self.assertEqual(rows[0]['enabled'],'false')

    def test_alias_uses_target(self):
        rows=self.parse('<application><activity android:name=".A" android:process=":a"/><activity-alias android:name=".Alias" android:targetActivity=".A"/></application>')
        self.assertEqual(rows[1]['effective_process'],'com.test:a')

    def test_unknown_alias_and_resource(self):
        rows=self.parse('<application><activity-alias android:name=".Alias" android:targetActivity=".Absent"/><service android:name=".S" android:process="@string/process"/></application>')
        self.assertIsNone(rows[0]['effective_process'])
        self.assertIsNone(rows[1]['effective_process'])

    def test_empty_apk_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'empty.apk'; path.touch()
            with self.assertRaises(ValueError): apk_inventory(path)

    def test_missing_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'bad.apk'
            with zipfile.ZipFile(path,'w') as archive: archive.writestr('classes.dex',b'test')
            with self.assertRaises(ValueError): apk_inventory(path)


if __name__=='__main__': unittest.main()
